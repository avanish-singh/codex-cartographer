function data = load_dataset(path)
% LOAD_DATASET Read a CSV of measurements; last column is the target.
    if ~isfile(path)
        error('Dataset not found: %s', path);
    end
    data = readmatrix(path);
    data = data(~any(isnan(data), 2), :);
end
