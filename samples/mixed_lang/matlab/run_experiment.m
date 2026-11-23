% run_experiment.m
% Script entry point: loads data, fits a model, reports metrics, plots results.

clear; clc;
addpath('utils');

data = load_dataset('data/measurements.csv');
[X, y] = engineer_features(data);

params = fit_linear_model(X, y);
y_hat = X * params;

rmse = compute_rmse(y, y_hat);
fprintf('RMSE: %.4f\n', rmse);

figure;
plot(y, y_hat, 'o');
xlabel('measured'); ylabel('predicted');
title('Linear model fit');
