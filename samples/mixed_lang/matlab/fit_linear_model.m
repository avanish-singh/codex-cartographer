function params = fit_linear_model(X, y)
% FIT_LINEAR_MODEL Ordinary least squares with a bias column.
%   params = fit_linear_model(X, y) returns the coefficient vector.

    n = size(X, 1);
    Xb = [ones(n, 1), X];
    params = Xb \ y;
    params = params(2:end);
end
