# analysis.R — bootstrap confidence interval for a mean.
library(stats)

load_scores <- function(path) {
  df <- read.csv(path)
  df$score
}

bootstrap_mean <- function(x, n_boot = 1000) {
  means <- replicate(n_boot, mean(sample(x, replace = TRUE)))
  quantile(means, c(0.025, 0.975))
}

main <- function() {
  scores <- load_scores("data/scores.csv")
  ci <- bootstrap_mean(scores)
  cat("95% CI:", ci, "\n")
  plot(density(scores), main = "Score density")
}

main()
