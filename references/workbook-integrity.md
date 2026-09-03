# 工作簿完整性与内嵌图片

在解释工作簿业务含义前，先把直接错误、格式候选、模板重复候选和视觉证据分开。

## 完整性扫描

```text
python scripts/data_lens.py workbook-integrity <files.xlsx...> --output workbook-integrity.json
```

扫描是只读且有单表格单元上限。结果区分：

- 公式错误：单元格直接状态，可作为数据质量事实；
- 陈旧 used range：声明范围小于实际非空范围，是解析风险；
- 数值绝对值大于 1 且按百分比显示：只是字段定义或格式复核候选，增长率超过 100% 可能完全合理；
- 跨工作簿完全相同的长文本：只是模板复用候选，不能自动称为串档；
- 配置词命中：只有在任务提供了目标范围或审核词表时使用 `--term-rules`，命中仍需人工确认是否超出当前对象范围。

`scan_truncated=true` 是强边界：此时 `observed_dimension` 只是已扫描区域的下界，公式错误数量也只是下界，二者都不能用来设置业务聚合的最大行。业务分析必须独立读取声明范围或完整数据记录，并保留空行/尾部样式的防护。若工作表缺少 dimension 元数据，结果会标记 `declared_dimension_status=missing_unsized`，脚本仍做有界扫描，不会为了合成范围强制无界遍历。

不要把某次项目中的产品名、行业词或固定工作表行号写入全局规则。通用脚本保存位置和边界，领域判断留在本轮规则或证据卡中。

## WPS 单元格图片

```text
python scripts/data_lens.py workbook-media <files.xlsx...> --manifest workbook-media.json
python scripts/data_lens.py workbook-media <files.xlsx...> --manifest workbook-media.json --extract-sample --output-dir visual-sample --max-images 12
```

脚本把 `DISPIMG` ID、单元格、OOXML 媒体对象和哈希连接起来。默认样本按工作簿和工作表分层，并在组内分散位置，禁止顺序取前几张。清点与抽取都不是 OCR 或语义审核；只有完成实际视觉复核的图片才能进入视觉证据卡。
