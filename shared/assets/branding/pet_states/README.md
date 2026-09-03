# 冰子形象源素材

此目录是冰子新增形象的 canonical 源素材目录。开发者只应在这里添加
经过确认的 PNG 文件；Windows 与 Android 不直接从此目录读取运行时资源。

固定文件名：

- `pain.png`：高速落地后的疼痛形象。
- `scared.png`：持续滞空超过 3 秒的害怕形象。
- `sleep.png`：稳定不动超过 30 秒的睡眠形象。
- `hungry.png`：饱食度为 0 的饥饿形象。
- `happy/happy1.png`、`happy/happy2.png`、……：快速双击提示形象组。

添加或替换 PNG 后，在仓库根目录运行：

```powershell
python tools/prepare_pet_appearance_assets.py
```

该工具会校验文件名和 PNG 签名，将通过校验的文件复制到
`shared/assets/pets/states/`，并生成运行资源清单。它不会修改共享契约中的
阈值或优先级；能力只有在清单完整、`priorityConfirmed` 已确认且三端 manifest
同步后才能启用。

当前提交没有新增形象 PNG，因此所有新增形象触发器保持 disabled，运行时继续
使用现有 `shared/assets/pets/bingzi.png` 与 `bingzi-left.png`。

## 资源设计约束

- 源文件必须是带透明背景的 PNG，并保持与现有冰子显示尺寸兼容。
- 不要把 `R.drawable`、Tkinter 对象或文件路径放入 domain/application。
- happy 组由资源工具按数字后缀排序；domain 只接收排序后的资源键，不调用
  `listdir`。
- 每次新增形象都要同步 Windows、Android、共享契约、测试和 GitHub PR。
