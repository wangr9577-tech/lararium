# 白板书写体验第四阶段：GPU AI 个性化美化

> 状态：研究与实施方案，前三阶段验收前不应进入生产开发  
> 依赖：高保真原始采样、确定性矢量美化、可逆数据结构  
> 核心原则：AI 异步、受约束、可撤回、可关闭；任何失败都回退第三阶段

## 1. 阶段目标

使用服务器 GPU 运行小型矢量模型，学习用户自己的书写习惯，在停笔或完成一组笔画后提供可选的个性化修正。

AI 不参与 pen-down 到湿墨显示的实时链路。用户看到的即时笔迹永远由本地第二阶段管线产生；第三阶段提供可靠美化；AI 只是更高层的异步增强。

### 1.1 首期能力

- 矢量轨迹去噪和轻微形态修正；
- 压力曲线个性化；
- 同一用户不同笔画之间的稳定风格；
- 返回置信度和几何约束指标；
- 自动低强度应用或手动预览；
- 原笔、确定性结果、AI 结果三者可切换。

### 1.2 暂不承诺

- 不承诺把“难看的字”自动变成书法。
- 不承诺识别所有中文、公式、图形和混合内容。
- 不用生成模型猜测用户没写出的笔画。
- 不把整词栅格生成结果覆盖矢量笔迹。
- 不在没有用户确认的数据上自动训练个人模型。

## 2. 开源方案评估

### 2.1 DiffusionPen

[DiffusionPen](https://github.com/koninik/DiffusionPen) 是 ECCV 2024 的少样本手写文本生成模型，可从少量参考图学习书写风格。

不适合直接用于实时白板：

- 基于 Stable Diffusion 1.5，输出是栅格文本图像；
- 主要围绕 IAM 英文数据评估；
- 生成的是“新的文字图像”，不是对用户原始矢量轨迹做受约束修正；
- 可能改变字形、间距或内容；
- 无法自然处理公式、箭头和草图。

可借鉴其 style encoder 思路，用于提取个人风格向量；也可作为“导出时生成仿手写排版”的独立实验，但不能放入主书写链路。

### 2.2 PaddleOCR

[PaddleOCR](https://github.com/PaddlePaddle/PaddleOCR) 可用于：

- 判断一组笔画更像文字还是图形；
- 行/词区域分割；
- 搜索索引；
- 美化前后字符一致性的辅助检查。

OCR 结果不能作为唯一真值，也不能直接触发字体替换。低置信度、公式和混合语言区域必须跳过语义修正。

### 2.3 SketchRNN/Magenta

[Magenta.js](https://github.com/magenta/magenta-js) 中的草图生成思想适合研究序列建模，但常见 SketchRNN 模型面向物体草图，不保存真实 pressure/tilt，也不适合作为中文笔迹修正器。

### 2.4 结论

生产首选不是现成生成模型，而是自建一个小型、输出残差的矢量去噪网络。它只预测“如何轻微移动有有点”，由确定性后处理器限制结果。

## 3. GPU 资源与调度规范

在共享服务器或多卡环境中部署时，不应在代码中硬编码任何特定卡号。部署时必须：

- 遵守服务器现有调度或管理员分配；
- 用独立环境变量指定 `CUDA_VISIBLE_DEVICES`；
- AI 服务启动前检查可用显存；
- 不与有有推理服务争用同一张有占满的卡；
- GPU 不可用时自动回退第三阶段。

## 4. 服务架构

```text
Browser
  |
  | POST /api/ai/ink/beautify（有有登录鉴权）
  v
Kruskal FastAPI
  |- 校验请求、限流、超时、去日志敏感数据
  |- 转发到 127.0.0.1 内网 sidecar
  v
Ink AI Service（独立进程/环境）
  |- 模型常驻显存
  |- 批量为 1，低延迟优先
  |- 输出点残差、压力残差、置信度
  v
Deterministic Constraint Guard
  |- 锚点、位移、拓扑和语义一致性检查
  v
Browser revision check -> 预览/应用/丢弃
```

### 4.1 为什么使用 sidecar

不要在当前 uvicorn 站点进程中导入 PyTorch：

- 会显著增加站点进程启动时间和内存；
- 模型崩溃或 CUDA OOM 会影响博客主功能；
- 当前 `backend/requirements.txt` 很轻，不应被 CUDA 依赖污染；
- sidecar 可独立重启、预热、选择 GPU 和升级模型。

## 5. 模块与文件

### 5.1 Kruskal 仓库

```text
backend/app/routers/ink_ai.py
backend/app/services/ink_ai_client.py
frontend/src/whiteboard/ai/InkBeautifyClient.ts
frontend/src/whiteboard/ai/InkAiQueue.ts
frontend/src/whiteboard/ai/types.ts
```

`backend/app/main.py` 注册 `ink_ai.router`。路由继续受全局 `/api` Bearer 鉴权保护，并显式使用 `Depends(get_current)` 与现有风格一致。

### 5.2 独立推理服务

建议单独目录或独立仓库：

```text
ink-ai-service/
├── app.py
├── schemas.py
├── inference.py
├── constraints.py
├── models/
├── training/
├── tests/
├── requirements.lock.txt
└── ink-ai.service
```

模型权重不提交 Git。使用受信任的 `safetensors` 或显式 state dict，禁止加载用户上传的 pickle。

## 6. API 设计

### 6.1 浏览器到 Kruskal

`POST /api/ai/ink/beautify`

```json
{
  "request_id": "uuid",
  "document_revision": 18,
  "page_id": "page-1",
  "stroke_group_id": "group-uuid",
  "mode": "personal",
  "strength": 0.25,
  "model_version": "auto",
  "strokes": [
    {
      "id": "stroke-uuid",
      "revision": 3,
      "tool": "pen",
      "width": 0.0026,
      "samples": [[0.1, 0.2, 0.52, 0, 3, -12, 0]]
    }
  ]
}
```

紧凑数组顺序由 API version 固定。服务端校验后转换成内部张量。

响应：

```json
{
  "ok": true,
  "request_id": "uuid",
  "model_version": "ink-denoiser-0.1.0",
  "confidence": 0.91,
  "strokes": [
    {
      "id": "stroke-uuid",
      "revision": 3,
      "samples": [[0.1, 0.2, 0.51, 0]]
    }
  ],
  "metrics": {
    "max_shift_px": 1.1,
    "topology_changed": false,
    "semantic_check": "skipped"
  }
}
```

失败统一返回 `{ "ok": false, "reason": "..." }`，与现有 AI 路由风格一致。前端不得因 AI 失败弹出高频错误或阻止保存。

### 6.2 限制

- 单请求压缩前最大 2MB；
- 单请求最多 64 笔、20000 个样本；
- 所有数值必须有限且在合理范围；
- 站点到 sidecar 超时建议 1.5 秒；
- 前端超过 800ms 仍无结果时不自动替换，只允许稍后手动查看；
- 同一用户并发请求上限 2，后续请求合并或取消旧请求。

## 7. 模型设计

### 7.1 输入特征

每个样本使用：

- `dx, dy`，而非绝对页面坐标；
- 速度、加速度、局部曲率；
- pressure 和 pressure 差分；
- tiltX/tiltY 的正余弦表示；
- twist；
- 相对时间；
- pen-up/stroke-boundary mask；
- 笔宽和笔刷类型；
- 可选个人 style embedding。

坐标按局部笔画包围盒和物理笔宽归一化，但必须保存逆变换。

### 7.2 首选架构

轻量序列残差模型：

```text
Feature projection
  -> 1D convolution stem
  -> 4～6 层 Transformer Encoder 或 TCN
  -> residual heads:
       delta_x, delta_y
       delta_pressure
       confidence
       anchor_probability
```

建议规模：10M～40M 参数。对现代主流显卡而言推理负担很小，主要延迟来自网络、序列预处理和服务排队。

模型不直接输出绝对新轨迹，只输出受限残差：

```text
refined = raw + strength * boundedResidual
```

### 7.3 约束后处理

无论模型置信度多高，都必须执行第三阶段的确定性检查：

- 端点和关键锚点最大位移；
- 全局最大位移；
- 自交和开闭状态；
- 包围盒和弧长变化；
- 压力范围和变化率；
- 笔画数量、顺序、ID 不变。

违反硬约束时降低 strength 重试一次；仍失败则返回第三阶段结果。

## 8. 请求粒度

### 8.1 单笔模式

- `pointerup` 后 150～300ms debounce；
- 适合轨迹去噪和压力个性化；
- 延迟短、语义风险最低；
- 作为首期唯一自动模式。

### 8.2 字符/词组模式

根据时间间隔和空间重叠，把连续笔画组成组：

- 中文字符通常由多笔组成，单笔无法判断整体结构；
- 数学符号和英文连写也需要多笔上下文；
- 分组错误会引入更大风险，因此只做显式预览或低强度修正。

### 8.3 行模式

可用于基线、字距和大小一致性，但最容易改变个人风格。不得默认启用，适合用户选择一行后执行“整理”。

## 9. 训练数据

### 9.1 通用预训练

首期目标是去噪而非文字生成，可以使用干净轨迹构造合成退化：

- 高频坐标抖动；
- 采样丢失和不均匀采样；
- 速度相关漂移；
- 起笔/收笔压力尖峰；
- 局部过冲；
- 轻微倾角噪声。

目标是恢复原轨迹。任何外部在线手写数据集在使用前必须单独审查许可证、再分发和商业使用条款，不把“GitHub 可下载”等同于可训练部署。

### 9.2 个人化数据

只在用户明确开启“参与个人笔迹学习”后收集：

- 用户接受的 AI/确定性结果；
- 用户恢复原笔的负反馈；
- 用户手动重新书写后的对应样本；
- 不含笔记标题和页面文本，只保存必要轨迹。

个人样本沿用 Kruskal vault 加密存储，不写入普通服务日志。

### 9.3 个性化方式

从低风险到高风险：

1. 仅估计用户压力曲线和滤波参数，不训练神经网络。
2. 学习一个固定维度 style embedding。
3. 对通用模型训练小型 adapter/LoRA。
4. 数据足够后才考虑完整 fine-tune。

个人数据少于可靠阈值时，不显示“有学会你的字迹”之类误导性文案。

## 10. OCR 与语义保护

OCR 是辅助保护，不是生成来源。

可选流程：

1. 把某个笔画组以低分辨率临时栅格化。
2. 使用本地 OCR 得到 top-k 和置信度。
3. 对原笔和 AI 结果分别识别。
4. 若原笔高置信度、AI 结果字符发生变化，则拒绝 AI 结果。
5. 任一侧低置信度、检测为公式/图形或混合内容时跳过语义判断，只使用几何约束。

OCR 图像只在内存中存在，不落盘、不记录到日志。

## 11. 前端状态管理

### 11.1 请求状态

```ts
interface InkAiJob {
  requestId: string
  documentRevision: number
  strokeRevisions: Record<string, number>
  status: 'queued' | 'running' | 'ready' | 'applied' | 'discarded' | 'failed'
  createdAt: number
}
```

收到响应时必须验证：

- 当前仍是同一文档；
- 页面和 stroke 仍存在；
- document revision 没有发生冲突；
- 每条 stroke revision 与请求时相同；
- 用户没有撤销、擦除或手动重新美化。

任何一项不满足都丢弃响应。

### 11.2 应用语义

- 低强度单笔模式可自动应用，但必须保留原始版本。
- 字符、词组、行模式默认只显示预览。
- 自动应用不新增撤销步骤；显式“应用 AI 美化”新增一步。
- 自动保存只保存最终有接受版本，不因排队中的请求延迟。

## 12. 推理服务实现

### 12.1 技术栈

- Python 3.11；
- PyTorch + CUDA；
- FastAPI/uvicorn 或轻量 gRPC/HTTP 服务；
- `safetensors`；
- 独立 conda/venv；
- systemd 管理和健康检查。

### 12.2 生命周期

启动时：

1. 检查分配 GPU 和显存。
2. 加载指定 model version。
3. 执行一次 warmup。
4. 健康检查通过后接收流量。

运行时：

- batch size 1，低延迟优先；
- 限制最大序列长度；
- CUDA OOM 捕获后清理缓存并进入短暂熔断；
- 记录耗时、队列长度、模型版本，不记录坐标内容；
- 模型热更新采用先加载新实例、健康检查后切换。

### 12.3 进程隔离

建议端口只监听 `127.0.0.1`，例如 `8001`。不对公网暴露，不复用有有的 OpenAI 接口。

## 13. 可靠性与安全

- AI 开关默认关闭，需在设置中显式启用。
- sidecar 不可用时返回 `ok: false`，前端继续使用第三阶段结果。
- 请求和响应均有大小、点数、数值范围限制。
- 模型输出再次校验，不能信任神经网络产生的任意数值。
- 不把笔迹样本写入 access log、exception body 或监控标签。
- 个人训练任务与在线推理解耦，训练 OOM 不影响在线服务。
- 模型文件使用校验值和固定版本，支持回滚。

## 14. 评价体系

### 14.1 离线指标

- 平均/最大点位移；
- Chamfer/Hausdorff 距离；
- 自交变化率；
- 端点和锚点偏移；
- 压力曲线误差；
- 合成噪声恢复误差；
- 可选 OCR 一致率。

### 14.2 在线指标

- 请求端到端 P50/P95/P99；
- sidecar 推理时间和排队时间；
- 自动应用率；
- 用户恢复原笔率；
- 用户手动接受率；
- 约束拒绝率；
- 超时、OOM 和降级率。

在线指标只记录统计值，不记录具体笔迹。

### 14.3 主观盲测

随机展示：原笔、第三阶段、美化模型三个版本，评价：

- 是否仍像本人；
- 是否更稳定；
- 是否改变字符；
- 是否出现不自然的统一模板感；
- 是否愿意自动应用。

“OCR 更容易识别”不能替代用户偏好。

## 15. 实施步骤

### P4.0 可行性门槛

- 前三阶段全部验收。
- 有积累高质量 raw samples。
- 明确 GPU 使用权限和部署位置。
- 建立离线轨迹评测集。

不满足这些条件则不开始模型开发。

### P4.1 无神经网络的个人参数

- 学习 pressure gamma、平滑强度和笔刷参数。
- 用接受/恢复行为更新参数。
- 验证“个性化”是否仅靠参数就能满足需求。

### P4.2 通用矢量去噪模型

- 构造合成噪声训练集。
- 训练残差模型。
- 离线通过几何不变量和盲测。
- 仅提供手动预览。

### P4.3 在线 sidecar

- 实现服务、鉴权代理、限流、健康检查和熔断。
- 只开放给单笔请求。
- 默认关闭自动应用。

### P4.4 个人 style embedding

- 增加明确 opt-in。
- 加密保存反馈样本。
- 达到样本阈值后训练或更新 embedding。
- A/B 比较通用与个性化结果。

### P4.5 字符/行级实验

- 加入笔画分组和可选 OCR 保护。
- 只在显式选择后运行。
- 不进入默认自动链路，直到长期数据证明安全。

## 16. 时间预估

| 工作 | 预估 |
|---|---|
| 数据回放、指标和训练管线 | 4～7 天 |
| 通用小模型原型 | 1～2 周 |
| sidecar、代理和可靠性 | 4～7 天 |
| 个人化和反馈闭环 | 1～2 周 |
| 中文/公式混合内容长期评估 | 持续迭代 |

时间不包含外部数据集许可审批和大规模标注。

## 17. 发布与回滚

独立 feature flags：

```text
ink_ai_enabled
ink_ai_auto_single_stroke
ink_ai_group_preview
ink_ai_personalization
ink_ai_ocr_guard
```

发布顺序：内部手动预览 → 单笔低强度自动 → 个性化 opt-in → 字符/行级实验。

任何模型版本都必须支持立即回滚。关闭 AI 后文档仍可使用 raw/第三阶段结果正常加载、编辑、保存和导出。

## 18. 验收清单

- [ ] AI 不进入实时湿墨链路。
- [ ] sidecar 与 Kruskal Web 进程隔离。
- [ ] GPU 不硬编码，遵守资源分配并可在无 GPU 时降级。
- [ ] 原始、确定性和 AI 三个版本均可恢复。
- [ ] 模型只能输出受限残差，经过确定性约束守卫。
- [ ] 撤销、擦除或 revision 改变后，旧 AI 响应不会覆盖新内容。
- [ ] AI 失败、超时、OOM 或关闭时不影响书写和保存。
- [ ] 个人样本明确 opt-in、加密保存、不进入普通日志。
- [ ] 几何指标、盲测偏好和语义保护均达到上线门槛。
- [ ] 模型和服务均可独立版本化及回滚。

