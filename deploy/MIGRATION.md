# 迁移到新服务器（10 分钟级）
> 设计原则：配置无绝对路径硬编码（环境变量覆盖）；数据 = backend/data 一个目录；前端为静态产物。

## 步骤

1. **新服务器装基础环境**
   ```bash
   conda create -y -n site python=3.11 pip
   # 常规安装（跟随 requirements 版本下限）：
   /path/to/miniconda3/envs/site/bin/pip install -i https://pypi.tuna.tsinghua.edu.cn/simple -r backend/requirements.txt
   # 可选·完全复现现网版本（锁文件由 pip freeze 生成，优先走清华镜像再回落默认源）：
   # /path/to/miniconda3/envs/site/bin/pip install -i https://pypi.tuna.tsinghua.edu.cn/simple -r backend/requirements.lock.txt
   cd frontend && npm install --registry=https://registry.npmmirror.com && npm run build && cd ..
   ```
   > 前端新增依赖 `dompurify`（P1-XSS 净化层），node_modules 过期时重新 npm install 即可。

2. **拷数据**（整站代码随仓库走，只多拷数据）
   ```bash
   # 旧机备份（交互输入备份口令；产物 .tar.gz.enc + .sha256 成对保存）
   ./deploy/backup.sh
   # 新机还原（先自动 sha256 校验，再解密解包；旧 data 保留为 data.bak-*，不物理删）
   ./deploy/restore.sh backups/kruskal-data-xxxx.tar.gz.enc
   # 或直接 rsync backend/data（服务停止时才可整目录直拷，否则 site.db-wal 可能撕裂）
   ```
   > 备份口令与网站主密码相互独立，忘记备份口令 = 备份不可恢复；建议与备份分处两地保管。

3. **启动**
   ```bash
   KRUSKAL_DATA_DIR=/新路径/data bash backend/start.sh
   # 或直接默认路径启动；监听地址端口用 KRUSKAL_HOST / KRUSKAL_PORT 控制（默认 127.0.0.1:18080）
   # 开发热重载：KRUSKAL_DEV=1 bash backend/start.sh（生产勿开，重载即锁库）
   ```

4. 迁移后可用浏览器验证：登录 → 各页数据是否完整；无需迁移任何加密密钥（.kek 随 data 目录一起走）。

## 可选：systemd 开机自启

```bash
sudo cp deploy/kruskal.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now kruskal
```
