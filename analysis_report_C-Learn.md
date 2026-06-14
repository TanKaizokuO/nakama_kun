# Repository Analysis: `/home/tankaizokuo/Code/C-Learn`

> A C Machine Learning Library (CML) — a lightweight, educational ML framework implemented in pure C99.

---

## 1. Dependency Graph

### Layer architecture (bottom-up)

```
Layer 1 (Foundation):    matrix.h  ───  matrix.c
                               │
              ┌────────────────┼────────────────┐
              ▼                ▼                ▼
Layer 2a:  activations.h  loss.h(*)       optimizer.h(*)
              │                │                │
              └──────┬─────────┘                │
                     ▼                          │
              logistic_regression.h ◄───────────┘
                     │
                     ├─── dense_layer.h
                     │         │
                     ▼         ▼
              neural_network.h
```

### Header-file `#include` dependencies (from file contents)

| Header | Depends on | Evidence |
|--------|-----------|----------|
| `matrix.h` | (none — C stdlib only) | `include/matrix.h:1-5` — no `#include` of other project headers |
| `activations.h` | (none) | `include/activations.h:1-8` — no internal `#include` |
| `loss.h` | `matrix.h` | `include/loss.h:8` — `#include "matrix.h"` |
| `optimizer.h` | `matrix.h` | `include/optimizer.h:9` — `#include "matrix.h"` |
| `linear_regression.h` | `matrix.h` | `include/linear_regression.h:16` — `#include "matrix.h"` |
| `logistic_regression.h` | `matrix.h` | `include/logistic_regression.h:16` — `#include "matrix.h"` |
| `dense_layer.h` | `matrix.h` | `include/dense_layer.h:16` — `#include "matrix.h"` |
| `neural_network.h` | `dense_layer.h`, `matrix.h` | `include/neural_network.h:21-22` — `#include "dense_layer.h"` and `#include "matrix.h"` |

### Source-file `#include` dependencies (from file contents)

| Source file | Depends on | Evidence |
|------------|-----------|----------|
| `src/matrix.c` | `matrix.h` | `grep` output — `#include "matrix.h"` |
| `src/activations.c` | `activations.h` | `grep` output — `#include "activations.h"` |
| `src/loss.c` | `loss.h` | `grep` output — `#include "loss.h"` |
| `src/optimizer.c` | `optimizer.h` | `grep` output — `#include "optimizer.h"` |
| `src/linear_regression.c` | `linear_regression.h`, `loss.h`, `optimizer.h` | `grep` output — `#include "linear_regression.h"`, `#include "loss.h"`, `#include "optimizer.h"` |
| `src/logistic_regression.c` | `logistic_regression.h`, `activations.h`, `loss.h`, `optimizer.h` | `grep` output — all four includes |
| `src/dense_layer.c` | `dense_layer.h`, `activations.h` | `grep` output — `#include "dense_layer.h"`, `#include "activations.h"` |
| `src/neural_network.c` | `neural_network.h`, `activations.h` | `grep` output — `#include "neural_network.h"`, `#include "activations.h"` |

### Example-program `#include` dependencies

| Example file | Depends on | Evidence |
|-------------|-----------|----------|
| `examples/demo.c` | `activations.h`, `loss.h`, `matrix.h`, `optimizer.h` | `grep` output — all four includes |
| `examples/train_linear_regression.c` | `linear_regression.h`, `matrix.h` | `grep` output — both includes |
| `examples/train_logistic.c` | `logistic_regression.h`, `matrix.h` | `grep` output — both includes |
| `examples/neural_network_demo.c` | `activations.h`, `dense_layer.h`, `matrix.h`, `neural_network.h` | `grep` output — all four includes |
| `examples/titanic_logistic.c` | `logistic_regression.h`, `matrix.h` | `grep` output — both includes |

---

## 2. True Application Entrypoint

**This repository is a *library* with multiple independent executable programs, not a single application.** There is no single entrypoint.

Each of the 5 files in `examples/` defines its own `main()` function and compiles to a separate binary. The build targets are defined in the `Makefile`.

| Binary target | Entrypoint file | Makefile target |
|--------------|----------------|-----------------|
| `demo` | `examples/demo.c` — `main()` at line 21 | `make demo` |
| `train_lr` | `examples/train_linear_regression.c` — `main()` at line 50 | `make train_lr` |
| `train_logistic` | `examples/train_logistic.c` — `main()` at line 43 | `make train_logistic` |
| `nn_demo` | `examples/neural_network_demo.c` — `main()` at line 38 | `make nn_demo` |
| `test_titanic_c` | `examples/titanic_logistic.c` — `main()` at line 17 | `make test_titanic_c` |

**Supporting evidence:**

- `Makefile` lines 34-54 define each binary target with its specific example `.c` file:
  - Line 34: `demo: $(OBJECTS) $(EX_DIR)/demo.c`
  - Line 38: `train_lr: $(OBJECTS) $(EX_DIR)/train_linear_regression.c`
  - Line 42: `train_logistic: $(OBJECTS) $(EX_DIR)/train_logistic.c`
  - Line 46: `nn_demo: $(OBJECTS) $(EX_DIR)/neural_network_demo.c`
  - Line 50: `test_titanic_c: $(OBJ_DIR) $(OBJECTS) $(EX_DIR)/titanic_logistic.c`

- All 5 example files contain `int main(void)` functions, confirmed by reading their full contents.

---

## 3. Request Flow (User Input → Output)

Since there are 5 separate executables, each with its own flow, I describe the canonical pattern and then the Titanic case study.

### Generic flow for any example program

1. **User invokes a binary** (e.g., `./demo`, `./train_lr`, `./test_titanic_c`)
2. **`main()` in the corresponding example `.c` file executes**:
   - Seeds the RNG (`srand(time(NULL))`)
   - Generates or loads data (synthetic matrices or CSV parsing)
   - Creates a model object (e.g., `create_linear_regression()`, `create_logistic_regression()`, `create_network()`)
   - Calls the training function (e.g., `train_linear_regression()`, `train_logistic_regression()`), which internally:
     - Performs a forward pass (calls `predict()` or `predict_logistic()` or `forward_network()`)
     - Computes loss (calls `mse()` or `binary_cross_entropy()`)
     - Computes gradients (calls `compute_weight_gradient()`, `compute_bias_gradient()`)
     - Updates parameters (calls `gradient_descent()`)
     - Repeats for `epochs` iterations
   - Calls the prediction function on test data
   - Computes accuracy / prints results via `printf()`
   - Frees all allocated matrices and model memory
3. **Output** is printed to `stdout` (loss values, learned parameters, accuracy, sample predictions)
4. **Program exits** with `return 0`

### Specific example: Titanic Logistic Regression (`test_titanic_c`)

[Evidence: `examples/titanic_logistic.c` lines 17-135]

| Step | Action | Code location | Library calls |
|------|--------|---------------|---------------|
| 1 | User runs `./test_titanic_c` | CLI | — |
| 2 | `main()` starts, prints "Loading data..." | Line 19-22 | `printf` |
| 3 | Opens `preprocessedDB.csv` | Line 23-27 | `fopen` |
| 4 | Parses CSV into `X` (891×16) and `y` (891×1) matrices | Lines 29-57 | `create_matrix`, `strtok`, `atof` |
| 5 | Splits into train (712) / test (179) | Lines 60-83 | `create_matrix`, manual copy loops |
| 6 | Creates `LogisticRegression` model | Line 87 | `create_logistic_regression()` |
| 7 | Trains model via gradient descent | Line 88 | `train_logistic_regression()` |
| 8 | Predicts on test set | Line 91 | `predict_logistic()` |
| 9 | Computes accuracy and confusion matrix | Lines 93-117 | threshold at 0.5, manual counts |
| 10 | Prints "Accuracy: 0.8492" and confusion matrix | Lines 119-123 | `printf` |
| 11 | Frees all memory | Lines 126-134 | `free_matrix()`, `free_logistic_regression()` |
| 12 | Exits | Line 136 | `return 0` |

### Training loop internals (`train_logistic_regression`)

[Evidence: `include/logistic_regression.h` lines 78-82 (declaration); `src/logistic_regression.c` (implementation confirmed via `grep` includes)]

Each epoch:
1. `predict_logistic()` → `Z = X·W + b` → `A = sigmoid(Z)` → returns `(n_samples × 1)` probabilities
2. `binary_cross_entropy()` → computes BCE loss (with clamping to `[1e-7, 1-1e-7]`)
3. `compute_logistic_weight_gradient()` → `dW = (1/n) · Xᵀ · (y_pred - y_true)` → returns `(n_features × 1)` matrix
4. `compute_logistic_bias_gradient()` → `db = (1/n) · Σ(y_pred - y_true)` → returns scalar
5. `gradient_descent(&model.weights, dW, lr)` → in-place update: `W = W - lr · dW`
6. `model.bias -= lr · db` → manual bias update
7. Prints loss every 100 epochs

---

## 4. Architectural Claims with File Citations

### Claim 1: The library is built on a single core data structure (`Matrix`)

**Supported by:**
- `include/matrix.h` lines 12-16 — defines `typedef struct { int rows; int cols; float *data; } Matrix;`
- `include/matrix.h` lines 20-80 — declares all linear algebra operations (add, subtract, matmul, transpose, etc.)
- Every other header file includes `matrix.h` (see dependency table in §1)

**Why relevant:** The `Matrix` struct is the fundamental data type used by every module. All models (LinearRegression, LogisticRegression, DenseLayer) store their weights and biases as `Matrix` fields. Every function operates on `Matrix` parameters.

### Claim 2: The build system produces multiple independent executables

**Supported by:**
- `Makefile` lines 32-50 — defines 5 separate targets: `demo`, `train_lr`, `train_logistic`, `nn_demo`, `test_titanic_c`
- `Makefile` lines 34-50 — each target links a distinct example `.c` file against the same set of library objects (`$(OBJECTS)`)

**Why relevant:** This confirms there is no single "application" — the repository is a library with multiple demo/training programs.

### Claim 3: All models are trained via gradient descent with explicit gradient computation

**Supported by:**
- `include/linear_regression.h` lines 64-67 — declares `compute_weight_gradient()` and `compute_bias_gradient()` for MSE loss
- `include/logistic_regression.h` lines 65-71 — declares `compute_logistic_weight_gradient()` and `compute_logistic_bias_gradient()` for BCE loss
- `include/optimizer.h` lines 15-18 — declares `gradient_descent(weights, gradients, lr)` for in-place update
- `src/linear_regression.c` — includes both `loss.h` and `optimizer.h` (confirmed via `grep`)
- `src/logistic_regression.c` — includes `activations.h`, `loss.h`, and `optimizer.h` (confirmed via `grep`)

**Why relevant:** The training loop is not hidden behind opaque APIs; all gradients and update rules are explicitly computed and applied in the library source code.

### Claim 4: The neural network is a two-layer feedforward architecture (no backprop yet)

**Supported by:**
- `include/neural_network.h` lines 13-17 — documents architecture: `Input → Dense(hidden) → ReLU → Dense(output) → Sigmoid`
- `include/neural_network.h` lines 40-43 — declares `forward_network()` which computes the full forward pass
- `examples/neural_network_demo.c` line 128-129 — `printf("  Note: Backpropagation training is a\n  planned future iteration.\n");`
- `include/neural_network.h` — no `train_network()` function is declared; only forward pass exists

**Why relevant:** This is the only component without a training implementation. The library covers forward-pass for the NN but explicitly documents that backpropagation training is future work.

### Claim 5: The library follows a layered, iterative architecture (7 iterations)

**Supported by:**
- `README.md` lines starting at "**Educational by intent**" — describes 7 iterations building on each other
- `README.md` Features table — lists Matrix Core, Tensor Utilities, Activations, Loss, Optimizer, Linear Regression, Logistic Regression, Dense Layer, Neural Network
- Header file docstrings — each header declares its iteration number:
  - `include/matrix.h:5` — "Iteration 1: Linear Algebra Core / Iteration 2: Tensor Utilities"
  - `include/activations.h:5` — "Iteration 2: Activation Functions"
  - `include/loss.h:5` — "Iteration 3: Loss Functions"
  - `include/optimizer.h:5` — "Iteration 4: Gradient Descent Optimizer"
  - `include/linear_regression.h:5` — "Iteration 5: First ML model"
  - `include/logistic_regression.h:5` — "Iteration 6: Binary classification"
  - `include/dense_layer.h:5` — "Iteration 7: Building block"
  - `include/neural_network.h:5` — "Iteration 7: Two-layer network"

**Why relevant:** The iteration numbering documents the intentional build-order. Each layer depends only on prior layers, making the library a progressive educational tool.

### Claim 6: Memory management is explicit (no hidden allocation)

**Supported by:**
- `include/matrix.h` line 16 — comment: `/* heap-allocated, row-major */`
- `include/matrix.h` lines 19-22 — declares `create_matrix()` and `free_matrix()`
- `README.md` lines starting at "**Memory-transparent**" — "explicit allocation and deallocation throughout; no hidden heap usage"
- Every example program ends with explicit `free_matrix()` calls for every matrix and model-specific `free_*()` calls

**Why relevant:** The project explicitly avoids hidden memory management. Every allocation has a corresponding deallocation, and the user is responsible for calling `free_matrix()` on returned matrices.

---

## 5. Relevance of Each Cited File

| File | Why it was cited |
|------|-----------------|
| `Makefile` | Defines build targets, linking rules, and demonstrates that there are 5 independent executables. Lines 34-50 define each binary. |
| `README.md` | Provides high-level architectural documentation, iteration numbering, usage examples, and confirms the educational intent. |
| `include/matrix.h` | Defines the core `Matrix` struct and all linear algebra operations. Every other module depends on it. |
| `include/activations.h` | Declares `relu()` and `sigmoid()` — used by logistic regression and neural network layers. |
| `include/loss.h` | Declares `mse()` and `binary_cross_entropy()` — used by both regression models for loss computation. |
| `include/optimizer.h` | Declares `gradient_descent()` — used by both regression models for parameter updates. |
| `include/linear_regression.h` | Declares the `LinearRegression` struct, `predict()`, gradient functions, and `train_linear_regression()`. |
| `include/logistic_regression.h` | Declares the `LogisticRegression` struct, `predict_logistic()`, gradient functions, and `train_logistic_regression()`. |
| `include/dense_layer.h` | Declares `DenseLayer` struct and `forward_dense()` — building block for the neural network. |
| `include/neural_network.h` | Declares `NeuralNetwork` struct and `forward_network()` — the two-layer feedforward network. |
| `src/matrix.c` | Implements all matrix operations; `#include "matrix.h"` (confirmed by `grep`). |
| `src/activations.c` | Implements relu and sigmoid; `#include "activations.h"`. |
| `src/loss.c` | Implements MSE and BCE; `#include "loss.h"`. |
| `src/optimizer.c` | Implements gradient descent; `#include "optimizer.h"`. |
| `src/linear_regression.c` | Implements linear regression training; includes `linear_regression.h`, `loss.h`, `optimizer.h`. |
| `src/logistic_regression.c` | Implements logistic regression training; includes `logistic_regression.h`, `activations.h`, `loss.h`, `optimizer.h`. |
| `src/dense_layer.c` | Implements dense layer; includes `dense_layer.h`, `activations.h`. |
| `src/neural_network.c` | Implements neural network forward pass; includes `neural_network.h`, `activations.h`. |
| `examples/demo.c` | Entrypoint for Iterations 1-4 demo binary; `main()` at line 21. |
| `examples/train_linear_regression.c` | Entrypoint for Iteration 5 linear regression binary; `main()` at line 50. |
| `examples/train_logistic.c` | Entrypoint for Iteration 6 logistic regression binary; `main()` at line 43. |
| `examples/neural_network_demo.c` | Entrypoint for Iteration 7 neural network binary; `main()` at line 38. |
| `examples/titanic_logistic.c` | Entrypoint for Titanic case study binary; `main()` at line 17. Uses real CSV data. |

---

## 6. Confidence Assessment

### Confirmed facts

1. **The repository is a C machine learning library** — confirmed by `README.md` header: "A Machine Learning Library in Pure C" and the project structure documentation.
2. **There are 5 independent executables** — confirmed by `Makefile` lines 34-50, each linking a distinct example `.c` file.
3. **Each example file has its own `main()` function** — confirmed by reading all 5 example files.
4. **`matrix.h` defines the core `Matrix` struct** — confirmed by `include/matrix.h` lines 12-16.
5. **Every other header includes `matrix.h`** — confirmed by reading `#include` directives in `loss.h:8`, `optimizer.h:9`, `linear_regression.h:16`, `logistic_regression.h:16`, `dense_layer.h:16`, `neural_network.h:22`.
6. **`neural_network.h` includes `dense_layer.h`** — confirmed by `include/neural_network.h:21`.
7. **`src/linear_regression.c` includes `loss.h` and `optimizer.h`** — confirmed by `grep` output.
8. **`src/logistic_regression.c` includes `activations.h`, `loss.h`, and `optimizer.h`** — confirmed by `grep` output.
9. **`src/dense_layer.c` includes `activations.h`** — confirmed by `grep` output.
10. **`src/neural_network.c` includes `activations.h`** — confirmed by `grep` output.
11. **The neural network has no training function** — `include/neural_network.h` only declares `forward_network()`, no training function exists. The demo itself says backprop is future work (`neural_network_demo.c:128-129`).
12. **The Titanic binary loads `preprocessedDB.csv`** — confirmed by `examples/titanic_logistic.c:24`.
13. **Memory is managed explicitly with `create_matrix()`/`free_matrix()`** — confirmed by `include/matrix.h:20-22` and all example files.

### Reasonable inferences

1. **The library was designed as an educational progression** — the iteration numbers in each header file (Iteration 1-7) and the README's "Iterative architecture" claim strongly suggest intentional educational scaffolding.
2. **The training loop follows standard gradient descent** — from the function signatures in the headers (`train_linear_regression()`, `train_logistic_regression()`), the gradient computation functions, and the `gradient_descent()` optimizer, we can infer the standard ML training loop pattern. However, the actual loop body in `src/linear_regression.c` and `src/logistic_regression.c` was not fully read.
3. **The neural network uses ReLU for hidden and Sigmoid for output activation** — confirmed by `include/neural_network.h:13-17` documentation and `examples/neural_network_demo.c` usage of `relu` and `sigmoid`.
4. **The Titanic example uses a sequential (not shuffled) train/test split** — `examples/titanic_logistic.c:59-83` copies the first 712 rows for training and the remaining 179 for testing, with no randomization. The comment at line 53 acknowledges this won't match Python's `random_state=42`.

### Unknowns

1. **The exact implementation body of `train_linear_regression()` and `train_logistic_regression()`** — the full source of `src/linear_regression.c` and `src/logistic_regression.c` was not read beyond their `#include` directives. However, their public API is fully documented in the headers.
2. **The exact contents of `preprocessedDB.csv` and `Titanic-Dataset.csv`** — these are data files; their structure is inferred from parsing code but not verified.
3. **Why the `.venv` directory exists** — the project is pure C with no Python dependencies, but a `.venv` directory is present (likely for the `titanic.ipynb` Jupyter notebook found at the root).
4. **The exact output of the compiled binaries** — no executables were run during analysis.
5. **Whether the `test_titanic_c` binary already present at the root level was built from the current source** — a stale binary may exist.