#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Wed Feb 25 20:31:12 2026

@author: avanish
"""

import os, math, json, gc
import numpy as np
import pandas as pd
import joblib
import matplotlib.pyplot as plt
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import RobustScaler
import tensorflow as tf
from tensorflow import keras
import optuna

# Check for Optuna pruning
try:
    from optuna.integration import TFKerasPruningCallback
    HAS_PRUNE = True
except Exception:
    HAS_PRUNE = False

# =========================================
# CONFIGURATION
# =========================================
CSV_PATH = "/home/avanish/CompiledData/vrtulsrc_exploss/combineData/VrtulsrcData_Vg0.5_1.6_Tox_1.csv"
ARTIFACT_DIR = "/home/avanish/CompiledData/vrtulsrc_exploss/vrtl_src_exploss_attemp1"
os.makedirs(ARTIFACT_DIR, exist_ok=True)

# Tuning Settings
N_TRIALS = 51
TUNE_EPOCHS = 400
TUNE_PATIENCE = 50

# Final Training Settings
SEEDS = [42, 7, 123, 2025]
FINAL_EPOCHS = 1500
FINAL_PATIENCE = 150
WARMUP_EPOCHS = 15

# =========================================
# UTILITIES & CALLBACKS
# =========================================
def set_global_seed(seed: int):
    np.random.seed(seed)
    tf.random.set_seed(seed)

def gelu(x):
    return tf.nn.gelu(x)

class CosineWithWarmup(keras.callbacks.Callback):
    def __init__(self, base_lr, epochs, warmup_epochs=10, min_lr=1e-6):
        super().__init__()
        self.base_lr = base_lr
        self.epochs = epochs
        self.warmup_epochs = warmup_epochs
        self.min_lr = min_lr

    def on_epoch_begin(self, epoch, logs=None):
        if epoch < self.warmup_epochs:
            lr = self.base_lr * (epoch + 1) / self.warmup_epochs
        else:
            progress = (epoch - self.warmup_epochs) / (self.epochs - self.warmup_epochs)
            lr = self.min_lr + 0.5 * (self.base_lr - self.min_lr) * (1 + math.cos(math.pi * progress))
        
        self.model.optimizer.learning_rate = float(lr)

class EMAWeights(keras.callbacks.Callback):
    def __init__(self, decay=0.999):
        super().__init__()
        self.decay = decay
        self.ema_weights = None

    def on_train_begin(self, logs=None):
        self.ema_weights = [w.numpy() for w in self.model.trainable_weights]

    def on_batch_end(self, batch, logs=None):
        for i, w in enumerate(self.model.trainable_weights):
            self.ema_weights[i] = self.decay * self.ema_weights[i] + (1 - self.decay) * w.numpy()

    def apply_to(self, model):
        if hasattr(model, 'base_model'):
            for w, ew in zip(model.base_model.trainable_weights, self.ema_weights):
                w.assign(ew)
        else:
            for w, ew in zip(model.trainable_weights, self.ema_weights):
                w.assign(ew)

# === CUSTOM EXPONENTIAL LOSS ===
# Penalizes errors exponentially to ensure the difference between ANY two points
# is locked in tightly, protecting your exp(Pred2 - Pred1) post-processing.
@tf.keras.utils.register_keras_serializable()
def exp_loss(y_true, y_pred):
    error = tf.clip_by_value(tf.abs(y_true - y_pred), 0.0, 20.0)
    return tf.reduce_mean(tf.math.exp(error) - 1.0)

# =========================================
# PHYSICS & SOBOLEV MODULE
# =========================================
def compute_numerical_gradients(df, feature_cols, target_col):
    print("--- [Physics] Computing Numerical Gradients for Sobolev Training ---")
    df = df.copy()
    grad_cols = []
    
    for f in feature_cols:
        other_features = [col for col in feature_cols if col != f]
        df = df.sort_values(by=other_features + [f])
        
        dy = df.groupby(other_features, group_keys=False)[target_col].diff()
        dx = df.groupby(other_features, group_keys=False)[f].diff()
        
        grad = dy / dx.replace(0, np.nan)
        
        df['temp_grad'] = grad
        df['temp_grad'] = df.groupby(other_features, group_keys=False)['temp_grad'].bfill()
        df['temp_grad'] = df.groupby(other_features, group_keys=False)['temp_grad'].ffill()
        df['temp_grad'] = df['temp_grad'].fillna(0.0)
        
        grad_col_name = f'grad_{f}'
        df[grad_col_name] = df['temp_grad']
        grad_cols.append(grad_col_name)
        
    df.drop(columns=['temp_grad'], inplace=True)
    return df, grad_cols

def generate_synthetic_vd_zero(df):
    print("--- [Physics] Generating Synthetic Vd=0 Data (Granular) ---")
    target_col = df.columns[-1]
    feature_cols = [c for c in df.columns if c not in ['Vd', target_col]]
    
    df_01 = df[df['Vd'] == 0.1].copy().set_index(feature_cols)[target_col]
    df_02 = df[df['Vd'] == 0.2].copy().set_index(feature_cols)[target_col]
    
    combined = pd.concat([df_01, df_02], axis=1, keys=['y_0.1', 'y_0.2']).dropna()
    
    vg_values = combined.index.get_level_values('Vg')
    conditions = [
        vg_values <= 0.8,                 
        np.isclose(vg_values, 0.9),       
        vg_values > 0.9                   
    ]
    choices = [1.995, 2.1, 2.16]
    factors = np.select(conditions, choices, default=2.16)
    
    combined['y_0.0'] = (factors * combined['y_0.1']) - combined['y_0.2']
    
    new_data = combined[['y_0.0']].reset_index()
    new_data['Vd'] = 0.0
    new_data.rename(columns={'y_0.0': target_col}, inplace=True)
    new_data = new_data[df.columns]
    
    augmented_df = pd.concat([df, new_data], ignore_index=True)
    print(f"Augmented size: {len(augmented_df)}")
    return augmented_df

def engineer_features(df):
    print("--- [Features] Engineering cross-terms and exponentials ---")
    df["Vg_times_Vd"] = df["Vg"] * df["Vd"]
    df["Vg_minus_Vd"] = df["Vg"] - df["Vd"]
    df["Vg_sq"] = df["Vg"] ** 2
    df["Vd_sq"] = df["Vd"] ** 2
    df["Exp_neg_Vd"] = np.exp(-df["Vd"])
    return df

def get_sample_weights(df):
    weights = np.ones(len(df), dtype=np.float32)
    mask_boundary = df["Vd"] <= 0.1
    weights[mask_boundary] = 10.0 
    return weights

# =========================================
# DATA LOADING & PREPROCESSING
# =========================================
if not os.path.exists(CSV_PATH):
    raise FileNotFoundError(f"Missing {CSV_PATH}")

print("Loading Data...")
df_raw = pd.read_csv(CSV_PATH)
df_raw.rename(columns={'V_g': 'Vg', 'V_d': 'Vd'}, inplace=True)

# 1. DROP CONSTANT FEATURES
if 'T_ox' in df_raw.columns and df_raw['T_ox'].nunique() == 1:
    print("--- [Preprocessing] Dropping constant feature 'T_ox' ---")
    df_raw.drop(columns=['T_ox'], inplace=True)

tgt_name = df_raw.columns[-1]

# === PHYSICAL SCALING (No arbitrary magnification needed) ===
# Divides the original physical target by 0.026 (Thermal Voltage). 
# This naturally magnifies the data by ~38.46x, preventing float32 underflow, 
# and sets the network up to perfectly predict the exponent for your post-processing!
print(f"--- [Preprocessing] Physically scaling target '{tgt_name}' by dividing by 0.026 ---")
df_raw[tgt_name] = df_raw[tgt_name] / 0.026
# ============================================================

orig_features = list(df_raw.columns[:-1])
NUM_ORIG_FEATURES = len(orig_features)

df_aug = generate_synthetic_vd_zero(df_raw)
df_with_grads, grad_cols = compute_numerical_gradients(df_aug, orig_features, tgt_name)
df_eng = engineer_features(df_with_grads)
weights_full = get_sample_weights(df_eng)

feat_cols = [c for c in df_eng.columns if c not in [tgt_name] + grad_cols]
X_full = df_eng[feat_cols].values.astype(np.float32)

y_full = df_eng[[tgt_name] + grad_cols].values.astype(np.float32)
X_full_unscaled = X_full.copy()

X_tr, X_tmp, y_tr, y_tmp, w_tr, w_tmp, X_un_tr, X_un_tmp = train_test_split(
    X_full, y_full, weights_full, X_full_unscaled, test_size=0.2, random_state=42
)
X_val, X_te, y_val, y_te, w_val, w_te, X_un_val, X_un_te = train_test_split(
    X_tmp, y_tmp, w_tmp, X_un_tmp, test_size=0.5, random_state=42
)

scaler = RobustScaler()
X_tr_sc = scaler.fit_transform(X_tr)
X_val_sc = scaler.transform(X_val)
X_te_sc = scaler.transform(X_te)
joblib.dump(scaler, os.path.join(ARTIFACT_DIR, "scaler.pkl"))

scale_factors = scaler.scale_[:NUM_ORIG_FEATURES]

def scale_target_gradients(y, scales):
    y_new = y.copy()
    y_new[:, 1:] = y_new[:, 1:] * scales
    return y_new

y_tr_sc = scale_target_gradients(y_tr, scale_factors)
y_val_sc = scale_target_gradients(y_val, scale_factors)
y_te_sc = scale_target_gradients(y_te, scale_factors)

# =========================================
# CUSTOM Keras MODEL FOR SOBOLEV TRAINING
# =========================================
class SobolevModel(keras.Model):
    def __init__(self, base_model, num_orig_features, alpha=1.0, **kwargs):
        super().__init__(**kwargs)
        self.base_model = base_model
        self.num_orig_features = num_orig_features
        self.alpha = alpha  
        self.loss_tracker = keras.metrics.Mean(name="val_loss")
        self.mae_metric = keras.metrics.MeanAbsoluteError(name="val_mae")

    def compile(self, optimizer, loss, **kwargs):
        super().compile(optimizer=optimizer, **kwargs)
        self.loss_fn = loss if callable(loss) else keras.losses.get(loss)

    @property
    def metrics(self):
        return [self.loss_tracker, self.mae_metric]

    def train_step(self, data):
        if len(data) == 3:
            x, y, sample_weight = data
        else:
            x, y = data
            sample_weight = None

        y_true = tf.cast(y[:, 0:1], tf.float32)
        dy_true = tf.cast(y[:, 1:], tf.float32)

        with tf.GradientTape() as outer_tape:
            with tf.GradientTape() as inner_tape:
                inner_tape.watch(x)
                y_pred = self.base_model(x, training=True)
            
            dy_pred_full = inner_tape.gradient(y_pred, x)
            dy_pred = dy_pred_full[:, :self.num_orig_features] 

            # Task 1: Value Match (Uses Custom Exponential Loss)
            loss_y = self.loss_fn(y_true, y_pred)
            if sample_weight is not None:
                loss_y = loss_y * sample_weight
            loss_y = tf.reduce_mean(loss_y)

            # Task 2: Gradient Match (Strict MAE forces extrapolation trajectories)
            loss_dy = tf.reduce_mean(tf.abs(dy_true - dy_pred), axis=-1)
            if sample_weight is not None:
                loss_dy = loss_dy * sample_weight
            loss_dy = tf.reduce_mean(loss_dy)

            total_loss = loss_y + self.alpha * loss_dy

        trainable_vars = self.base_model.trainable_variables
        gradients = outer_tape.gradient(total_loss, trainable_vars)
        self.optimizer.apply_gradients(zip(gradients, trainable_vars))

        self.loss_tracker.update_state(total_loss)
        self.mae_metric.update_state(y_true, y_pred)
        
        return {"val_loss": self.loss_tracker.result(), "val_mae": self.mae_metric.result()}

    def test_step(self, data):
        if len(data) == 3:
            x, y, sample_weight = data
        else:
            x, y = data
            sample_weight = None

        y_true = tf.cast(y[:, 0:1], tf.float32)
        dy_true = tf.cast(y[:, 1:], tf.float32)

        with tf.GradientTape() as tape:
            tape.watch(x)
            y_pred = self.base_model(x, training=False)
            
        dy_pred_full = tape.gradient(y_pred, x)
        dy_pred = dy_pred_full[:, :self.num_orig_features] if dy_pred_full is not None else tf.zeros_like(dy_true)

        loss_y = self.loss_fn(y_true, y_pred)
        if sample_weight is not None:
            loss_y = loss_y * sample_weight
        loss_y = tf.reduce_mean(loss_y)

        loss_dy = tf.reduce_mean(tf.abs(dy_true - dy_pred), axis=-1)
        if sample_weight is not None:
            loss_dy = loss_dy * sample_weight
        loss_dy = tf.reduce_mean(loss_dy)

        total_loss = loss_y + self.alpha * loss_dy

        self.loss_tracker.update_state(total_loss)
        self.mae_metric.update_state(y_true, y_pred)

        return {"val_loss": self.loss_tracker.result(), "val_mae": self.mae_metric.result()}

    def call(self, inputs, training=False):
        return self.base_model(inputs, training=training)

# =========================================
# OPTUNA TUNING
# =========================================
def make_model(trial_or_params, input_dim):
    if hasattr(trial_or_params, "suggest_float"):
        trial = trial_or_params
        width = trial.suggest_categorical("width", [128, 256, 384, 512])
        depth = trial.suggest_int("depth", 2, 5)
        dropout = trial.suggest_float("dropout", 0.0, 0.2)
        l2 = trial.suggest_float("l2", 1e-6, 1e-3, log=True)
        lr = trial.suggest_float("lr", 1e-4, 5e-3, log=True)
        # Higher alpha forces Sobolev slopes to be respected, ensuring Extrapolation works!
        alpha = trial.suggest_float("alpha", 0.01, 1.0, log=True) 
    else:
        p = trial_or_params
        width = p["width"]
        depth = p["depth"]
        dropout = p["dropout"]
        l2 = p["l2"]
        lr = p["lr"]
        alpha = p.get("alpha", 0.1)

    inputs = keras.Input(shape=(input_dim,))
    x = inputs
    
    for _ in range(depth):
        res = x
        if x.shape[-1] != width: res = keras.layers.Dense(width)(res)
        x = keras.layers.Dense(width, kernel_regularizer=keras.regularizers.l2(l2))(x)
        x = keras.layers.BatchNormalization()(x)
        x = keras.layers.Activation(gelu)(x)
        if dropout > 0: x = keras.layers.Dropout(dropout)(x)
        x = keras.layers.Dense(width, kernel_regularizer=keras.regularizers.l2(l2))(x)
        x = keras.layers.BatchNormalization()(x)
        x = keras.layers.Add()([x, res])
        x = keras.layers.Activation(gelu)(x)
        
    outputs = keras.layers.Dense(1)(x)
    base_model = keras.Model(inputs, outputs)
    
    model = SobolevModel(base_model, num_orig_features=NUM_ORIG_FEATURES, alpha=alpha)
    opt = keras.optimizers.AdamW(learning_rate=lr, weight_decay=1e-4)
    
    # Compile using the Custom Exponential Loss
    model.compile(optimizer=opt, loss=exp_loss) 
    
    model(tf.zeros((1, input_dim)))
    return model

def objective(trial):
    tf.keras.backend.clear_session()
    model = make_model(trial, X_tr_sc.shape[1])
    
    batch_size = trial.suggest_categorical("batch_size", [32, 64, 128])
    lr = trial.params['lr']
    
    ema = EMAWeights(decay=0.99)
    scheduler = CosineWithWarmup(lr, TUNE_EPOCHS, warmup_epochs=10)
    
    callbacks = [
        keras.callbacks.EarlyStopping(monitor="val_loss", patience=TUNE_PATIENCE, restore_best_weights=True),
        scheduler, ema
    ]
    if HAS_PRUNE: callbacks.append(TFKerasPruningCallback(trial, "val_loss"))
    
    hist = model.fit(
        X_tr_sc, y_tr_sc, sample_weight=w_tr,
        validation_data=(X_val_sc, y_val_sc),
        epochs=TUNE_EPOCHS, batch_size=batch_size,
        callbacks=callbacks, verbose=0
    )
    return min(hist.history["val_loss"])

print("\n=== Phase 1: Optuna Tuning (Sobolev with Exponential Loss) ===")
study = optuna.create_study(direction="minimize")
study.optimize(objective, n_trials=N_TRIALS)

best_params = study.best_params
print("Best Params:", json.dumps(best_params, indent=2))
with open(os.path.join(ARTIFACT_DIR, "best_params.json"), "w") as f:
    json.dump(best_params, f)

with open(os.path.join(ARTIFACT_DIR, "optuna_study_summary.txt"), "w") as f:
    f.write(f"Best trial: {study.best_trial.number}\n")
    f.write(f"Best val Loss: {study.best_value:.6f}\n")
    f.write(json.dumps(study.best_trial.params, indent=2))

# =========================================
# FINAL TRAINING
# =========================================
print("\n=== Phase 2: Final Training ===")
best_val_score = float('inf')
preds_tr_list, preds_val_list, preds_te_list = [], [], []

best_seed_idx = -1
best_model_path = ""

for idx, seed in enumerate(SEEDS):
    print(f"--- Seed {seed} ---")
    set_global_seed(seed)
    model = make_model(best_params, X_tr_sc.shape[1])
    
    ema = EMAWeights(decay=0.999)
    scheduler = CosineWithWarmup(best_params['lr'], FINAL_EPOCHS, warmup_epochs=WARMUP_EPOCHS)
    
    callbacks = [
        keras.callbacks.ModelCheckpoint(
            os.path.join(ARTIFACT_DIR, f"model_seed{seed}.weights.h5"),
            save_weights_only=True, save_best_only=True, monitor="val_loss", verbose=0
        ),
        keras.callbacks.EarlyStopping(patience=FINAL_PATIENCE, restore_best_weights=True),
        scheduler, ema
    ]
    
    hist = model.fit(
        X_tr_sc, y_tr_sc, sample_weight=w_tr,
        validation_data=(X_val_sc, y_val_sc),
        epochs=FINAL_EPOCHS, 
        batch_size=best_params['batch_size'],
        callbacks=callbacks, verbose=1
    )
    
    ema.apply_to(model)
    val_loss = model.evaluate(X_val_sc, y_val_sc, verbose=0)[0]
    print(f"Seed {seed} Final Val Loss: {val_loss:.6f}")
    
    if val_loss < best_val_score:
        best_val_score = val_loss
        best_seed_idx = idx
        best_model_path = os.path.join(ARTIFACT_DIR, "best_model.keras")
        model.base_model.save(best_model_path)
        print(">>> New Best Sobolev Base Model Saved!")
        
    preds_tr_list.append(model.predict(X_tr_sc, verbose=0).flatten())
    preds_val_list.append(model.predict(X_val_sc, verbose=0).flatten())
    preds_te_list.append(model.predict(X_te_sc, verbose=0).flatten())
    
    hist_df = pd.DataFrame(hist.history)
    hist_df.to_csv(os.path.join(ARTIFACT_DIR, f"history_seed{seed}.csv"), index=False)
    
    plt.figure(figsize=(8,6))
    plt.plot(hist_df.get("val_loss", []), label="Val Target+Gradient Loss (Exp Loss)")
    plt.plot(hist_df.get("val_mae", []), label="Val Direct MAE", linestyle="--")
    plt.xlabel("Epoch"); plt.ylabel("Loss"); plt.title(f"Seed {seed} History")
    plt.legend(); plt.grid(True); plt.tight_layout()
    plt.savefig(os.path.join(ARTIFACT_DIR, f"loss_history_seed{seed}.png")); plt.close()

# =========================================
# REPORTING
# =========================================
print("\n=== Phase 3: Generating Reports ===")

ens_tr = np.mean(preds_tr_list, axis=0)
ens_val = np.mean(preds_val_list, axis=0)
ens_te = np.mean(preds_te_list, axis=0)

y_tr_clean = y_tr[:, 0]
y_val_clean = y_val[:, 0]
y_te_clean = y_te[:, 0]

def save_detailed_results(filename, X_un, y_true, y_pred, subset_name):
    df_res = pd.DataFrame(X_un, columns=feat_cols)
    
    # REVERSE SCALING: Multiply by 0.026 to bring the data back to its true physical dimension
    df_res['Actual_Physical'] = y_true * 0.026
    df_res['Predicted_Physical'] = y_pred * 0.026
    
    df_res['Abs_Error'] = np.abs(df_res['Actual_Physical'] - df_res['Predicted_Physical'])
    
    # Evaluate how far off the multiplier exp(y_true/0.026) vs exp(y_pred/0.026) is
    df_res['Exp_Processing_Error_%'] = np.abs(np.exp(y_true) - np.exp(y_pred)) / np.exp(y_true) * 100
    
    # Standard flawed APE retained for historical consistency
    df_res['APE_%'] = (df_res['Abs_Error'] / (np.abs(df_res['Actual_Physical']) + 1e-6)) * 100
    
    path = os.path.join(ARTIFACT_DIR, filename)
    df_res.to_csv(path, index=False)
    
    valid_exp_error = df_res['Exp_Processing_Error_%'][np.isfinite(df_res['Exp_Processing_Error_%'])]
    mape_exp = valid_exp_error.mean()
    print(f"[{subset_name}] Post-Processing Exponential Error (MAPE): {mape_exp:.4f}%")
    return df_res

print(f"Saving 'Best Seed' results from Seed {SEEDS[best_seed_idx]}")
df_tr_best = save_detailed_results("train_results.csv", X_un_tr, y_tr_clean, preds_tr_list[best_seed_idx], "BestSeed Train")
df_val_best = save_detailed_results("val_results.csv", X_un_val, y_val_clean, preds_val_list[best_seed_idx], "BestSeed Val")
df_te_best = save_detailed_results("test_results.csv", X_un_te, y_te_clean, preds_te_list[best_seed_idx], "BestSeed Test")

save_detailed_results("ensemble_train_results.csv", X_un_tr, y_tr_clean, ens_tr, "Ensemble Train")
save_detailed_results("ensemble_test_results.csv", X_un_te, y_te_clean, ens_te, "Ensemble Test")

def scatter_plot(y_true, y_pred, title, filename):
    plt.figure(figsize=(7, 7))
    
    # Reverse scaling for the plots
    y_true_plot = y_true * 0.026
    y_pred_plot = y_pred * 0.026
    
    plt.scatter(y_true_plot, y_pred_plot, alpha=0.4, s=15)
    max_val = max(y_true_plot.max(), y_pred_plot.max())
    min_val = min(y_true_plot.min(), y_pred_plot.min())
    plt.plot([min_val, max_val], [min_val, max_val], 'r--', linewidth=2)
    plt.xlabel("Actual (Physical)"); plt.ylabel("Predicted (Physical)")
    plt.title(title)
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(os.path.join(ARTIFACT_DIR, filename), dpi=150)
    plt.close()

scatter_plot(y_tr_clean, preds_tr_list[best_seed_idx], 
             "Actual vs Pred (Train - Best Model)", "actual_vs_pred_train.png")
scatter_plot(y_te_clean, preds_te_list[best_seed_idx], 
             "Actual vs Pred (Test - Best Model)", "actual_vs_pred_test.png")

plt.figure(figsize=(8, 8))
plt.scatter(y_tr_clean * 0.026, preds_tr_list[best_seed_idx] * 0.026, alpha=0.3, label='Train', s=10)
plt.scatter(y_te_clean * 0.026, preds_te_list[best_seed_idx] * 0.026, alpha=0.5, label='Test', s=10)
max_val = max(y_tr_clean.max() * 0.026, y_te_clean.max() * 0.026)
min_val = min(y_tr_clean.min() * 0.026, y_te_clean.min() * 0.026)
plt.plot([min_val, max_val], [min_val, max_val], 'r--', linewidth=2)
plt.xlabel("Actual (Physical)"); plt.ylabel("Predicted (Physical)")
plt.title("Actual vs Predicted (Train & Test)")
plt.legend(); plt.grid(True)
plt.savefig(os.path.join(ARTIFACT_DIR, "actual_vs_pred_train_test.png"))

print(f"\nAll Done! Results saved to: {os.path.abspath(ARTIFACT_DIR)}")
