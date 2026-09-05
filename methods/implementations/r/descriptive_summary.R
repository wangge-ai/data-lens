args <- commandArgs(trailingOnly = TRUE)
if (length(args) != 2) {
  stop("usage: descriptive_summary.R <input.csv> <output.json>")
}

input_path <- args[[1]]
output_path <- args[[2]]
data <- read.csv(input_path, check.names = FALSE, stringsAsFactors = FALSE, fileEncoding = "UTF-8")

json_escape <- function(value) {
  value <- gsub("\\\\", "\\\\\\\\", as.character(value))
  value <- gsub('"', '\\"', value, fixed = TRUE)
  value <- gsub("\n", "\\n", value, fixed = TRUE)
  value
}

json_number <- function(value) {
  if (length(value) == 0 || is.na(value) || is.nan(value) || is.infinite(value)) "null" else format(value, digits = 15, scientific = FALSE, trim = TRUE)
}

numeric_names <- names(data)[vapply(data, is.numeric, logical(1))]
results <- character(0)
for (name in numeric_names) {
  values <- data[[name]]
  observed <- values[!is.na(values)]
  body <- paste0(
    '{"column":"', json_escape(name), '",',
    '"count":', length(observed), ',',
    '"missing_count":', sum(is.na(values)), ',',
    '"mean":', json_number(if (length(observed)) mean(observed) else NA_real_), ',',
    '"minimum":', json_number(if (length(observed)) min(observed) else NA_real_), ',',
    '"maximum":', json_number(if (length(observed)) max(observed) else NA_real_), '}'
  )
  results <- c(results, body)
}

payload <- paste0(
  '{"contract_version":"data-lens-method-result/1.0",',
  '"method_id":"data_lens.r_descriptive_summary",',
  '"method_version":"0.1.1",',
  '"status":"', if (length(numeric_names)) 'succeeded' else 'ineligible', '",',
  '"results":[', paste(results, collapse = ","), '],',
  '"diagnostics":[{"numeric_column_count":', length(numeric_names), '}],',
  '"boundaries":["Descriptive statistics do not establish causality; missing values are not zeros."]}'
)

writeLines(payload, output_path, useBytes = TRUE)
