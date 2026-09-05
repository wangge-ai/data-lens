args <- commandArgs(trailingOnly = TRUE)
if (length(args) != 2) {
  stop("usage: time_trend_competition.R <input.csv> <output.json>")
}

input_path <- args[[1]]
output_path <- args[[2]]

json_escape <- function(value) {
  value <- enc2utf8(as.character(value))
  value <- gsub("\\", "\\\\", value, fixed = TRUE)
  value <- gsub('"', '\\"', value, fixed = TRUE)
  value <- gsub("\r", "\\r", value, fixed = TRUE)
  value <- gsub("\n", "\\n", value, fixed = TRUE)
  value
}

json_string <- function(value) paste0('"', json_escape(value), '"')
json_number <- function(value) {
  if (length(value) == 0 || is.na(value) || is.nan(value) || is.infinite(value)) {
    "null"
  } else {
    format(value, digits = 15, scientific = FALSE, trim = TRUE)
  }
}

emit_ineligible <- function(reason, observed_rows = 0, dropped_rows = 0) {
  payload <- paste0(
    '{"contract_version":"data-lens-method-result/1.0",',
    '"method_id":"data_lens.r_time_trend_competition",',
    '"method_version":"0.1.0",',
    '"status":"ineligible",',
    '"results":[],',
    '"diagnostics":[{"reason":', json_string(reason),
    ',"observed_rows":', observed_rows,
    ',"dropped_rows":', dropped_rows, '}],',
    '"boundaries":["Ineligible data do not support a trend comparison; no model conclusion was produced."]}'
  )
  writeLines(enc2utf8(payload), output_path, useBytes = TRUE)
  quit(save = "no", status = 0)
}

if (!requireNamespace("mgcv", quietly = TRUE)) {
  emit_ineligible("required local R package mgcv is unavailable")
}

data <- read.csv(input_path, check.names = FALSE, stringsAsFactors = FALSE, fileEncoding = "UTF-8")
if (!all(c("time", "value") %in% names(data))) {
  emit_ineligible("CSV must contain exact time and value columns")
}
if (!is.numeric(data$value)) {
  emit_ineligible("value must be numeric")
}

raw_time <- data$time
if (is.numeric(raw_time)) {
  numeric_time <- as.numeric(raw_time)
  time_scale <- "input_numeric_unit"
} else {
  parsed_time <- suppressWarnings(as.Date(as.character(raw_time)))
  numeric_time <- as.numeric(parsed_time)
  time_scale <- "calendar_day"
}

complete <- is.finite(numeric_time) & is.finite(data$value)
dropped_rows <- sum(!complete)
frame <- data.frame(time_value = numeric_time[complete], value = data$value[complete])
if (nrow(frame) < 15) {
  emit_ineligible("at least 15 complete time/value rows are required", nrow(frame), dropped_rows)
}
if (anyDuplicated(frame$time_value)) {
  emit_ineligible("duplicate time points require an explicit aggregation or repeated-measures design", nrow(frame), dropped_rows)
}
frame <- frame[order(frame$time_value), , drop = FALSE]
if (length(unique(frame$time_value)) < 15 || diff(range(frame$time_value)) == 0) {
  emit_ineligible("time must contain at least 15 distinct ordered values", nrow(frame), dropped_rows)
}
if (length(unique(frame$value)) < 3 || stats::sd(frame$value) == 0) {
  emit_ineligible("value must vary across at least three values", nrow(frame), dropped_rows)
}

train_n <- floor(nrow(frame) * 0.8)
holdout_n <- nrow(frame) - train_n
if (train_n < 10 || holdout_n < 3) {
  emit_ineligible("time-ordered split requires at least 10 training rows and 3 holdout rows", nrow(frame), dropped_rows)
}
train <- frame[seq_len(train_n), , drop = FALSE]
holdout <- frame[(train_n + 1):nrow(frame), , drop = FALSE]
origin <- min(train$time_value)
span <- max(train$time_value) - origin
train$time_index <- (train$time_value - origin) / span
holdout$time_index <- (holdout$time_value - origin) / span

linear_model <- stats::lm(value ~ time_value, data = train)
k_value <- min(10L, max(4L, floor(nrow(train) / 2)))
smooth_model <- mgcv::gam(value ~ s(time_index, k = k_value, bs = "cs"), data = train, method = "REML")

linear_prediction <- as.numeric(stats::predict(linear_model, newdata = holdout))
smooth_prediction <- as.numeric(stats::predict(smooth_model, newdata = holdout))
if (any(!is.finite(linear_prediction)) || any(!is.finite(smooth_prediction))) {
  emit_ineligible("one or both models produced non-finite holdout predictions", nrow(frame), dropped_rows)
}

rmse <- function(actual, predicted) sqrt(mean((actual - predicted)^2))
mae <- function(actual, predicted) mean(abs(actual - predicted))
linear_rmse <- rmse(holdout$value, linear_prediction)
smooth_rmse <- rmse(holdout$value, smooth_prediction)
linear_mae <- mae(holdout$value, linear_prediction)
smooth_mae <- mae(holdout$value, smooth_prediction)
loss_difference <- abs(holdout$value - smooth_prediction) - abs(holdout$value - linear_prediction)

set.seed(20260904)
block_length <- max(1L, min(length(loss_difference), floor(sqrt(length(loss_difference)))))
bootstrap_means <- replicate(2000, {
  block_starts <- sample(seq_along(loss_difference), ceiling(length(loss_difference) / block_length), replace = TRUE)
  indices <- unlist(lapply(block_starts, function(start) ((start - 1L + seq_len(block_length) - 1L) %% length(loss_difference)) + 1L))
  mean(loss_difference[indices[seq_along(loss_difference)]])
})
bootstrap_ci <- as.numeric(stats::quantile(bootstrap_means, c(0.025, 0.975), names = FALSE, type = 7))
preference <- if (bootstrap_ci[[2]] < 0) {
  "smooth_lower_mae"
} else if (bootstrap_ci[[1]] > 0) {
  "linear_lower_mae"
} else {
  "inconclusive"
}

linear_summary <- summary(linear_model)
linear_ci <- suppressMessages(stats::confint(linear_model, "time_value", level = 0.95))
smooth_summary <- summary(smooth_model)
smooth_p <- if (!is.null(smooth_summary$s.table)) smooth_summary$s.table[1, ncol(smooth_summary$s.table)] else NA_real_

result <- paste0(
  '{"analysis_type":"time_ordered_linear_vs_smooth_competition",',
  '"observed_rows":', nrow(frame), ',',
  '"dropped_rows":', dropped_rows, ',',
  '"time_scale":', json_string(time_scale), ',',
  '"split":{"strategy":"ordered_forward_holdout","training_rows":', train_n,
  ',"holdout_rows":', holdout_n, '},',
  '"linear_model":{"slope":', json_number(stats::coef(linear_model)[["time_value"]]),
  ',"slope_standard_error":', json_number(linear_summary$coefficients["time_value", "Std. Error"]),
  ',"slope_ci_95":[', json_number(linear_ci[[1]]), ',', json_number(linear_ci[[2]]), '],',
  '"holdout_rmse":', json_number(linear_rmse), ',"holdout_mae":', json_number(linear_mae), '},',
  '"smooth_model":{"package":"mgcv","basis":"shrinkage_cubic_regression_spline",',
  '"k":', k_value, ',"effective_degrees_of_freedom":', json_number(sum(smooth_model$edf)),
  ',"smooth_term_p_value":', json_number(smooth_p),
  ',"deviance_explained":', json_number(smooth_summary$dev.expl),
  ',"holdout_rmse":', json_number(smooth_rmse), ',"holdout_mae":', json_number(smooth_mae), '},',
  '"paired_holdout_loss":{"metric":"absolute_error_smooth_minus_linear",',
  '"mean_difference":', json_number(mean(loss_difference)),
  ',"bootstrap_ci_95":[', json_number(bootstrap_ci[[1]]), ',', json_number(bootstrap_ci[[2]]), '],',
  '"bootstrap_method":"circular_block","bootstrap_block_length":', block_length,
  ',"bootstrap_replicates":2000,"preference":', json_string(preference), '},',
  '"claim_level":"predictive_shape_comparison_not_causal"}'
)

payload <- paste0(
  '{"contract_version":"data-lens-method-result/1.0",',
  '"method_id":"data_lens.r_time_trend_competition",',
  '"method_version":"0.1.0",',
  '"status":"succeeded",',
  '"results":[', result, '],',
  '"diagnostics":[{"ordered_input":true,"duplicate_time_points":false,"mgcv_available":true}],',
  '"boundaries":[',
  '"Forward holdout error compares predictive time shapes; it does not identify a business mechanism or a causal effect.",',
  '"The paired circular-block bootstrap preserves only short local dependence and is a screening uncertainty estimate, not a time-series proof.",',
  '"A smooth-model win is a reason to inspect local turning behavior and competing drivers, not permission to extrapolate indefinitely."',
  ']}'
)

writeLines(enc2utf8(payload), output_path, useBytes = TRUE)
