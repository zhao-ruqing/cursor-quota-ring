# cursor-quota-ring

Windows 桌面叠加层：在 Cursor 左侧 Activity Bar 上显示用量圆环 + 百分比。

不是 Cursor 插件，而是跟随 Cursor 窗口的轻量桌面工具；按窗口的 `--user-data-dir` 自动绑定对应账号额度。

**仓库：** https://github.com/zhao-ruqing/cursor-quota-ring

![platform](https://img.shields.io/badge/platform-Windows%2010%2F11-0078D4)
![python](https://img.shields.io/badge/python-3.10%2B-3776AB)
![license](https://img.shields.io/badge/license-MIT-green)

## 功能

- 圆环 + 中间百分比（适配 150% / 200% DPI）
- 多账号：每个 Cursor 配置目录单独统计
- 自动把当前 Cursor 窗口映射到对应账号
- 支持 Cursor 3.27+ `cursor-safe-storage:v1:` token 解密（Windows DPAPI + AES-GCM）
- 同时支持普通编辑器窗口与 **Cursor Agents** 窗口（位置偏移可分别配置）
- 双屏：Cursor 在左屏时，鼠标在右屏操作仍可保持圆环显示
- 右键圆环：弹出另一账号额度卡片；鼠标离开后自动收起
- 可选开机自启；无 Electron 运行时

## 为什么不用 Pulse / CodeNotch / UsageBar？

| 工具 | 形态 | 缺口 |
|------|------|------|
| Pulse / CodeNotch | 屏幕边缘 notch，汇总账号 | 无法钉在某个 Cursor 窗口 Activity Bar 上 |
| UsageBar | 可拖拽条 | 不跟窗口绑定；可能漏掉自定义 profile 目录 |
| **cursor-quota-ring** | Activity Bar 叠加圆环 | 面向 Windows 双 Cursor 实例 |

Token / API 思路参考 [UsageBar](https://github.com/yavuzceliker/usagebar)（MIT）。

## 环境要求

- Windows 10 / 11
- Python **3.10+**（需带 **tkinter**）
- 已登录的 Cursor 桌面端（可多套配置目录）

```powershell
pip install -r requirements.txt
```

## 快速开始

```powershell
git clone https://github.com/zhao-ruqing/cursor-quota-ring.git
cd cursor-quota-ring

copy config.example.json config.json   # 按需改 profiles
pip install -r requirements.txt

# 检查账号 / 额度 / 窗口绑定
.\run.ps1 -Probe

# 前台运行（有控制台）
.\run.ps1

# 后台运行（无控制台）
.\run.ps1 -Hidden

# 可选：开机自启
.\install-startup.ps1
```

启动后，圆环会出现在 Cursor 左侧 Activity Bar 底部附近。  
同屏叠着编辑器与 Agents 时，圆环跟随**最前面的那个窗口**，并使用对应偏移。

### 右键查看另一账号

- 在圆环上**右键**：弹出另一账号的额度卡片（圆环 + 邮箱 / 套餐）
- 鼠标离开圆环或卡片后自动关闭
- 换号：在对应 Cursor 里重新登录即可，一般约 30 秒内刷新；**同一 `user-data-dir` 换号无需改配置**

## 双账号

Cursor 每个 `user-data-dir` 对应一套登录。第二套实例示例：

```powershell
& "$env:LOCALAPPDATA\Programs\cursor\Cursor.exe" `
  --user-data-dir="$env:USERPROFILE\CursorAccount2\data" `
  --extensions-dir="$env:USERPROFILE\CursorAccount2\extensions"
```

然后在 `config.json` 的 `profiles` 里写上两个目录（见 `config.example.json`）。  
若再增加第三套独立数据目录，同样在 `profiles` 里追加路径。

## 配置说明

| 字段 | 含义 |
|------|------|
| `overlay_size` | 96 DPI 下的圆环尺寸（随显示缩放） |
| `activity_bar_width` | Activity Bar 宽度（默认 `48`） |
| `bottom_offset` | 相对窗口客户区底部的距离，**越大越高**（编辑器） |
| `agents_bottom_offset` | Agents 窗口专用底部偏移（通常更靠下） |
| `metric` | `total` \| `auto` \| `api` |
| `click_through` | `true` 时点击穿透到 Cursor（右键查看会失效） |
| `foreground_only` | `true` 时仅当前焦点 Cursor 显示圆环；`false` 时双屏更友好（推荐） |
| `poll_seconds` | 用量 API 刷新间隔 |
| `reposition_ms` | 圆环跟随窗口的刷新间隔 |
| `profiles` | 各账号的 `user_data_dir` 列表 |

## 目录结构

```text
cursor-quota-ring/
  main.py                 # 入口
  _boot.py                # pythonw 启动封装（写 run.log）
  config.example.json     # 示例配置
  run.ps1                 # 启动 / probe / 后台
  install-startup.ps1     # 开机自启
  requirements.txt
  src/
    accounts.py           # 配置目录与 token 读取
    safe_storage.py       # cursor-safe-storage 解密
    usage_api.py          # GetCurrentPeriodUsage
    windows_track.py      # Cursor 窗口与 user-data-dir 绑定
    overlay.py            # 叠加层与多窗口跟随
    peek_popup.py         # 右键另一账号额度卡片
    ring_draw.py          # 抗锯齿圆环（Pillow）
```

## 说明与限制

- 使用 Cursor 未正式文档化的 Dashboard API，字段可能变化。
- Token 只留在本机；网络请求仅发往 Cursor API。
- Electron 窗口无法可靠 `SetParent` 子窗口，因此圆环是对齐 Activity Bar 的顶层窗口。
- 同屏最大化多个 Cursor 时，圆环按最前面窗口的模式（编辑器 / Agents）定位，避免错位。

## License

MIT
