# 品牌源资产

`app_image.png` 是 Windows 与 Android 共用的 canonical 应用图源文件，由项目所有者于 2026-08-25 提供。

`pet_image.png` 是冰子（Bingzi）的 canonical 多姿态源图；透明运行姿态由
`python tools/prepare_pet_asset.py` 生成到 `shared/assets/pets/bingzi.png`，并将
逐像素水平镜像生成到 `shared/assets/pets/bingzi-left.png`。
冰子新增状态图只放在 `shared/assets/branding/pet_states/`，由
`python tools/prepare_pet_appearance_assets.py` 校验并生成到
`shared/assets/pets/states/`；当前状态资源缺失，功能保持 disabled。
平台 UI 只加载运行资源，宠物位置和动画不进入 domain/application 或持久化。

平台图标应在各自最外层资源目录中由该文件生成，避免 `domain`、`application` 或词库内容依赖品牌图片。生成 Android adaptive icon 或 Windows ICO 时需保留此源文件，不得反向用低分辨率派生图覆盖。

`app_image.png` 信息：

- 格式：PNG（RGB，无透明通道）
- 尺寸：1254 x 1254
- SHA-256：`923365de4aebe9daa295dac74db76e0e76ab9d3bc1aa14a67f2af29fb4c65f80`

`pet_image.png` 信息：

- 格式：PNG（RGB，无透明通道）
- 尺寸：1254 x 1254
- SHA-256：`ff8ce536c8ebf69f9f8990c94115842ac7c6fe3fac867265b031c396d18ec124`

`shared/assets/pets/bingzi.png` 信息：

- 格式：PNG（RGBA，透明背景）
- 尺寸：650 x 660
- SHA-256：`eea2733972136eca55c20fa58d86add1e5378422028f72d2f1209d396c2a5fb7`

`shared/assets/pets/bingzi-left.png` 信息：

- 格式：PNG（RGBA，透明背景）
- 尺寸：650 x 660
- SHA-256：`e4b364dcd96c431df1962c3e9b12dc05f6787c1db52db330b43c07a7dea27294`
