# 白板书写体验第二阶段：低延迟采样与自然笔感

> 状态：实施方案，尚未编码  
> 依赖：第一阶段分层渲染已经完成并达到性能验收线  
> 核心原则：采样不能丢，湿墨不能等，滤波不能让笔尖产生明显拖拽感

## 1. 阶段目标

本阶段改善笔尖接触屏幕后到墨迹出现之间的感知延迟，并利用压感、速度和倾角让不同笔刷具有稳定、可预测的手感。

完成后的默认交互：

- 主动触控笔：书写；掌触忽略。
- 单指：平移。
- 双指：平移和缩放。
- 圆珠笔：稳定、接近恒定粗细。
- 钢笔：压感和方向共同影响笔锋。
- 马克笔：平头宽幅，方向稳定。
- 荧光笔：同一笔内部不因自交叠加变深。

## 2. 性能预算

| 环节 | P95 预算 |
|---|---|
| PointerEvent 到采样队列 | `< 1 ms` |
| 采样清洗与滤波 | `< 1 ms/批` |
| 湿墨几何更新 | `< 4 ms/帧` |
| 湿墨绘制提交 | `< 3 ms/帧` |
| 总 JS 热路径 | `< 8 ms` |
| 触控笔落下到首个可见点 | 支持 Delegated Ink 时争取 `< 16 ms`；回退路径 `< 32 ms` |

显示器刷新、操作系统合成和触控硬件延迟不由网页完全控制，因此指标必须同时记录 JS 延迟和真机端到端延迟。

## 3. 输入管线

```text
pointerdown
  -> 锁定 active pointerId
  -> 立即画起笔点
  -> 初始化设备档案和笔刷状态

pointerrawupdate（优先）/ pointermove（回退）
  -> getCoalescedEvents()
  -> 按 timeStamp 排序和去重
  -> 坐标转换
  -> 屏幕空间距离门限
  -> 压力/位置/倾角滤波
  -> 真实点进入 StrokeBuffer
  -> 湿墨绘制
  -> Delegated Ink 或预测尾迹

pointerup / pointercancel
  -> 吸收最后一批采样
  -> 清掉预测尾迹
  -> 完成最终轮廓
  -> 提交干墨层
```

## 4. 事件接入

### 4.1 事件选择

优先级：

1. 支持 `pointerrawupdate` 时，书写期间使用它接收低延迟原始事件。
2. 否则使用 `pointermove`。
3. 每个事件都读取 `getCoalescedEvents()`；为空时使用事件本身。
4. 不得同时把同一物理采样从 `pointerrawupdate` 和 `pointermove` 写入数据。

`pointerrawupdate` 建议通过 `addEventListener` 注册，不依赖 Vue 模板事件，以便精确控制启用、关闭和 feature detection。

### 4.2 去重

不同浏览器可能在主事件和 coalesced 列表中重复最后一点。使用以下组合去重：

```text
(pointerId, timeStamp, clientX, clientY, pressure)
```

若时间戳相同但坐标不同，保留全部点。若坐标完全相同，仅保留压力或倾角变化超过门限的点。

### 4.3 距离门限

tldraw 使用屏幕空间距离限制重复点。Kruskal 也应按当前缩放后的 CSS 像素判断，而不是页面归一化距离。

建议初值：

- 慢速书写：最小距离 `0.25 px`。
- 普通速度：`0.5 px`。
- 快速划线：`0.75～1.0 px`。
- 不允许使用固定 `5 px` 之类的大门限，会损伤小字和中文转折。

## 5. 采样数据

```ts
interface RawInkSample {
  x: number
  y: number
  pressure: number
  time: number
  tiltX: number
  tiltY: number
  twist: number
  tangentialPressure: number
  pointerType: string
  predicted: boolean
}
```

序列化时：

- `time` 保存相对笔画起点的毫秒数；
- `pressure` 至少保留 3 位小数，不能继续只保留 2 位；
- 倾角无设备支持时写默认值或省略；
- 预测点永远不进入持久化数据；
- 非有限数、越界坐标和异常时间戳在输入边界丢弃。

## 6. 低延迟湿墨

### 6.1 首点

`pointerdown` 后立即画圆点或短胶囊，不能等待第二个移动点。起笔点直径根据当前笔刷和压力计算。

### 6.2 实际点与预测点分层

live 层内部再区分：

- committed wet ink：已收到的真实采样；
- speculative tail：浏览器预测或应用预测产生的短尾巴。

收到真实采样后必须清掉旧预测尾迹，再用新预测重画，预测点不得污染最终路径。

### 6.3 Delegated Ink Trail

支持 `navigator.ink` 的 Chromium 环境优先使用 Delegated Ink Trail，由操作系统绘制尚未送达网页的最后几像素。

实现为独立适配器：

```ts
interface InkTailPresenter {
  init(area: HTMLElement): Promise<boolean>
  update(event: PointerEvent, color: string, diameter: number): void
  reset(): void
}
```

注意：

- API 仍需 feature detection，不绑定某个浏览器版本。
- presenter 只负责简单颜色、透明度和直径，最终复杂笔锋仍由应用绘制。
- 使用 Delegated Ink 时关闭应用预测，否则末端可能分叉。
- presenter 初始化失败必须静默回退。

参考：[WICG Web Ink Enhancement](https://github.com/WICG/ink-enhancement)。

### 6.4 预测回退

无 Delegated Ink 时：

1. 优先读取 `PointerEvent.getPredictedEvents()`。
2. 预测范围最多约 1 个显示帧。
3. 快速转弯、速度突变或即将抬笔时缩短预测。
4. 预测尾迹使用稍低透明度，避免修正时产生明显闪动。
5. 浏览器无预测 API 时，不在第一版自研复杂预测器；先保证真实采样低延迟。

## 7. 滤波策略

### 7.1 原则

- 滤波越强，抖动越少，但延迟越大。
- 小字和中文折角比长直线更怕过度平滑。
- 位置、压力和倾角不能使用同一组参数。
- 原始数据必须保留；滤波只影响渲染数据。

### 7.2 位置滤波

采用速度自适应低通滤波或 One Euro 思路：

- 低速时提高截止频率，保留细节和转折。
- 高速时加强去抖，稳定长线。
- 检测到曲率峰值时临时减弱平滑，避免圆角化横折。

不要直接复制无明确许可证的实现。根据公开算法公式实现一个小型、有测试的本地版本。

### 7.3 压力滤波

压力使用轻量 EMA，并特殊处理起笔和收笔：

```text
filteredP = alpha * currentP + (1 - alpha) * previousP
```

建议：

- 正常段 `alpha = 0.35～0.55`；
- 起笔前 2～4 个点限制突增，避免墨团；
- 收笔低压点不应把最后几像素突然压成针尖；
- 设备始终返回 0、0.5 或 1 时判定为无真实压感，转用速度模拟。

### 7.4 压力曲线

使用可配置 gamma 曲线：

```text
width = minWidth + (maxWidth - minWidth) * pressure^gamma
```

默认 `gamma` 可从 `0.7～1.1` 试验。不要直接把原始 pressure 线性映射到 0 宽度。

## 8. 笔刷设计

### 8.1 圆珠笔

- 粗细接近恒定；
- 压力只在较小范围影响宽度；
- 圆头、圆连接；
- 较低 smoothing，强调跟手；
- 无压感设备也不依赖速度产生过大的宽度变化。

### 8.2 钢笔

- 压力决定主宽度；
- 可选使用倾角和运动方向计算椭圆笔尖投影；
- 起笔和收笔使用短 taper；
- 转折处限制宽度突变；
- `perfect-freehand` 最终参数从当前固定值变为笔刷配置。

### 8.3 马克笔

- 使用固定笔尖方向或跟随 `twist/tilt`；
- 轮廓按平头笔尖生成，不只把圆笔刷乘 2.4；
- 没有 tilt 时使用用户设置的固定角度；
- 边缘保持稳定，不追求过多速度变化。

### 8.4 荧光笔

- 一笔先在透明离屏层中以不透明颜色绘制；
- 整笔完成后以目标 alpha 一次合成，避免自交处反复变深；
- 圆头/平头作为选项，但默认平头更接近真实荧光笔；
- 预测尾迹透明度必须与最终颜色足够接近。

## 9. 笔感档位

提供内部配置，UI 使用三段式控制：

| 档位 | 位置平滑 | 压力平滑 | 预测 | 适用 |
|---|---|---|---|---|
| 响应优先 | 最低 | 低 | 开 | 小字、快速批注 |
| 均衡 | 自适应 | 中 | 开 | 默认 |
| 平滑优先 | 较强 | 中高 | 保守 | 签名、慢速大字 |

档位必须影响采样和笔刷参数，而不是只改变 `perfect-freehand.smoothing` 一个值。

## 10. “触感”的可实现边界

Web 页面通常无法控制 Apple Pencil、S Pen 或 Windows 笔的硬件震动，也没有跨平台的笔尖 haptic API。`navigator.vibrate()` 不能精确作用于触控笔，iOS 支持也有限，不应作为核心方案。

可以改善的感知反馈：

- 落笔首点立即出现；
- 笔尖光标实时反映宽度和倾角；
- 压感变化连续，没有跳宽；
- 预测尾迹与真实笔迹无明显错位；
- 捏合、平移和掌触不会打断笔迹。

若未来要求真实硬件触觉，需要原生 Windows Ink、Android 原生笔 API 或 PencilKit 容器，不属于当前 Web 阶段。

## 11. 模块与文件

```text
frontend/src/whiteboard/input/
├── PointerInputController.ts
├── CoalescedEventReader.ts
├── SampleFilter.ts
├── PressureFilter.ts
├── DeviceProfile.ts
└── InkTailPresenter.ts

frontend/src/whiteboard/brushes/
├── types.ts
├── ballpoint.ts
├── fountain.ts
├── marker.ts
└── highlighter.ts
```

`WhiteboardCanvas.vue` 只接收控制器输出的规范化样本，不再直接在 `onMove()` 内处理全部采样细节。

## 12. 设备档案

不同设备的 pressure 行为不同。建立仅保存在本地浏览器的设备档案：

```ts
interface PenDeviceProfile {
  pressureMin: number
  pressureMax: number
  pressureGamma: number
  positionMode: 'responsive' | 'balanced' | 'smooth'
  supportsTilt: boolean
  supportsTwist: boolean
}
```

不要使用不稳定的硬件指纹标识用户。档案按浏览器本地默认值保存，用户可手动重置。

## 13. 实施步骤

### P2.1 高保真采样

- 接入 coalesced events。
- 增加时间、倾角、twist 数据。
- 做排序、去重、异常值过滤。
- 建立采样回放测试工具。

### P2.2 Raw input

- feature detect `pointerrawupdate`。
- 处理与 `pointermove` 的互斥。
- 验证 pointer capture、掌触和 pointercancel。

### P2.3 压感与位置滤波

- 实现可测试的自适应滤波器。
- 完成三档配置。
- 建立不同速度、折角、圆弧的黄金样本。

### P2.4 低延迟尾迹

- 先实现 `getPredictedEvents()` 回退。
- 再接入 Delegated Ink adapter。
- 保证二者互斥。

### P2.5 笔刷

- 圆珠笔和钢笔先上线。
- 再实现真正的平头马克笔和荧光笔合成。
- 每种笔刷单独调参与真机验收。

## 14. 测试矩阵

### 14.1 自动测试

- 合并事件按时间有序、无重复。
- 预测点不进入持久化数据。
- pressure 为 0、0.5、1 常量时正确判断无压感。
- pointerId 不匹配时不能修改当前笔迹。
- rawupdate 与 pointermove 不重复采样。
- 三种笔感档位输出稳定且参数可回滚。
- 荧光笔自交区域 alpha 不翻倍。

### 14.2 轨迹回放

保存不含文字语义的测试轨迹：

- 慢速横线；
- 快速斜线；
- 小圆；
- 连续锯齿；
- 中文横折钩式转角；
- 压力从低到高再降低；
- 倾角连续变化。

相同输入必须得到确定性输出。

### 14.3 真机测试

- 记录设备、浏览器、刷新率、采样率。
- 用高速摄像比较笔尖与墨迹距离。
- 检查快速折返时预测尾迹是否分叉。
- 手掌先落、笔后落；笔先落、手掌后落。
- 边写边触碰第二指，笔迹不得异常提交。

## 15. 发布与降级

每个能力单独 feature flag：

```ts
usePointerRawUpdate
useCoalescedEvents
useDelegatedInk
usePredictedEvents
useAdaptiveFilter
useTiltBrush
```

检测失败或发生异常时按以下路径降级：

```text
Delegated Ink
  -> 浏览器预测事件
  -> 仅 coalesced events
  -> 普通 pointermove
```

任何增强失败都不得阻止基本书写和保存。

## 16. 验收清单

- [ ] 高频触控笔采样不会因 RAF 合并而丢失。
- [ ] 起笔立即有墨迹，无需移动第二个点。
- [ ] 支持环境启用 Delegated Ink，失败时自动降级。
- [ ] 预测尾迹不写入文档，快速转弯无明显分叉。
- [ ] 圆珠笔、钢笔、马克笔、荧光笔的行为可辨识且稳定。
- [ ] 三个笔感档位在小字和长线测试中均无异常。
- [ ] 掌触、单指平移、双指缩放保持第一阶段行为。
- [ ] 自动化回放输出确定，生产构建通过。

