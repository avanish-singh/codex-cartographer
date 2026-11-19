#include <iostream>
#include <vector>
#include <cmath>
#include "../c/signal.h"

// Minimal gradient-descent trainer to give the atlas a C++ class hierarchy.
class Model {
public:
    virtual double predict(double x) const = 0;
    virtual void update(double grad, double lr) = 0;
    virtual ~Model() {}
};

class LinearModel : public Model {
public:
    LinearModel(double w, double b) : w_(w), b_(b) {}

    double predict(double x) const override {
        return w_ * x + b_;
    }

    void update(double grad, double lr) override {
        w_ -= lr * grad;
        b_ -= lr * grad * 0.1;
    }

private:
    double w_;
    double b_;
};

double mse_loss(const std::vector<double>& y_true, const std::vector<double>& y_pred) {
    double total = 0.0;
    for (size_t i = 0; i < y_true.size(); i++) {
        double diff = y_true[i] - y_pred[i];
        total += diff * diff;
    }
    return total / static_cast<double>(y_true.size());
}

void train(LinearModel& model, const std::vector<double>& xs, const std::vector<double>& ys, int epochs) {
    for (int epoch = 0; epoch < epochs; epoch++) {
        std::vector<double> preds;
        for (double x : xs) {
            preds.push_back(model.predict(x));
        }
        double loss = mse_loss(ys, preds);
        model.update(loss, 0.01);
        if (epoch % 10 == 0) {
            std::cout << "epoch " << epoch << " loss " << loss << std::endl;
        }
    }
}

int main() {
    std::vector<double> xs = {0, 1, 2, 3};
    std::vector<double> ys = {1, 3, 5, 7};
    LinearModel model(0.0, 0.0);
    train(model, xs, ys, 50);
    return 0;
}
