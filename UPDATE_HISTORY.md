# Update History / 更新历史

[README / 项目主页](README.md) · [中文使用说明](README.zh-CN.md)

## 0.7.4

标签仅在按住 Cmd（macOS）或 Ctrl（Windows/Linux）并拖动时移动；普通拖动平移画面，双击仍可改名。画布顶部和悬停提示显示对应按键。

MoonLabeler 0.7.4 requires Cmd (macOS) or Ctrl (Windows/Linux) while dragging to move a label. Ordinary drags pan the image; double-click still edits the text. The canvas header and tooltips show the platform-specific modifier.

## 0.7.3

小月盘的计算窗口允许排除边框附近、窗口外的成行文字，避免较大图注阻止识别。原图水印不修改；第二个明显目标、内部文字和孤立的大标志仍保守处理。已验证 DWARF 实拍添加图注后的变体，以及横向、纵向边框文字。背景亮度处理不变。

MoonLabeler 0.7.3 lets compact-disk window selection disregard small, aligned border-caption components outside the search window. Source watermarks remain untouched; substantial secondary objects, interior text and isolated large logos remain subject to conservative checks. Tested with a captioned DWARF photograph and horizontal/vertical border-text fixtures. Background-brightness handling is unchanged.

## 0.7.2

修复小月盘被大片黑边包围时的识别失败。对孤立的小亮区裁取计算窗口，保留原有纹理及几何验证，结果换回完整原图坐标；原图、保存和导出尺寸不变。已用 DWARF 实拍验证。文件名时区规则不变，本地时间仍需换算为 UTC。

MoonLabeler 0.7.2 fixes recognition of small lunar disks surrounded by large black margins. A bounded search window preserves texture and geometry validation, then restores original-image coordinates. Source pixels, saved projects and export dimensions are unchanged. Verified on a DWARF photograph; filename timezone rules are unchanged and local capture times still require conversion to UTC.

## 0.7.1

增加受限的手机目镜后畸变校正。已有可靠纹理匹配、但月缘检查失败时才尝试；需同时通过分区留出与真实受光月缘验证。原图不重采样，文字、坑缘和导出共用校正坐标。已验证一张实拍，不保证所有手机、目镜组合或局部照片都能识别。

MoonLabeler 0.7.1 adds a guarded afocal-phone distortion fallback after a strong atlas match fails its limb check. Spatial holdouts and the observed illuminated limb must both agree. Original pixels remain untouched; labels, crater outlines and exports share the corrected coordinates. Validated on one real afocal photograph, not a general success-rate claim. Distortion-aware projects require 0.7.1 or later and cannot serve as planar local-reference projects.

## 0.7.0

中文地名优先采用 LPND 资料；加入可选 wgpu 跨平台 GPU 后端，使用 Metal / Vulkan / DirectX 12 生成高程阴影参考。“计算设置”简化为自动与仅 CPU，并显示可用设备。已实测 Apple M5 Pro；NVIDIA、AMD、Intel 的硬件与驱动兼容性仍需对应机器验证。

MoonLabeler 0.7.0 prioritizes contributor-supplied LPND Chinese names and adds optional cross-platform wgpu terrain shading through Metal / Vulkan / DirectX 12. Compute settings offer Auto and CPU-only, with the detected device shown. Tested on Apple M5 Pro; NVIDIA, AMD and Intel hardware/driver compatibility still requires native validation.
