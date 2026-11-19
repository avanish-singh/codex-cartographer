function [X, y] = engineer_features(data)
% ENGINEER_FEATURES Build a feature matrix from the raw table.
    y = data(:, end);
    raw = data(:, 1:end-1);
    X = [raw, raw .^ 2, log1p(abs(raw))];
    X = normalize_columns(X);
end

function X = normalize_columns(X)
% Z-score each column so the solver is well conditioned.
    mu = mean(X, 1);
    sigma = std(X, 0, 1) + 1e-9;
    X = (X - mu) ./ sigma;
end
