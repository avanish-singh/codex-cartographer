function rmse = compute_rmse(y_true, y_pred)
% COMPUTE_RMSE Root-mean-square error between two vectors.
    residual = y_true - y_pred;
    rmse = sqrt(mean(residual .^ 2));
end
