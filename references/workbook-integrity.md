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

不要把某次项目中的产品名、行业词或固定工作表行号写入全局规则。通用脚本保存位置和边界，领域判断留在本轮规则或证据卡中。

## WPS 单元格图片

```text
python scripts/data_lens.py workbook-media <files.xlsx...> --manifest workbook-media.json
python scripts/data_lens.py workbook-media <files.xlsx...> --manifest workbook-media.json --extract-sample --output-dir visual-sample --max-images 12
```

脚本把 `DISPIMG` ID、单元格、OOXML 媒体对象和哈希连接起来。默认样本按工作簿和工作表分层，并在组内分散位置，禁止顺序取前几张。清点与抽取都不是 OCR 或语义审核；只有完成实际视觉复核的图片才能进入视觉证据卡。
