import pandas as pd
from sklearn.linear_model import LogisticRegression
import numpy as np

def train_model(csv_path: str = "scripts/data/calibration_data.csv"):
    print("🧠 Training Logistic Regression Model (Platt Scaling)...")
    
    # 1. Load the labeled data
    df = pd.read_csv(csv_path)
    
    # Clean data (ensure labels are numeric 0 or 1)
    df['LABEL_1_or_0'] = pd.to_numeric(df['LABEL_1_or_0'], errors='coerce')
    df = df.dropna(subset=['LABEL_1_or_0'])
    
    # 2. Extract Features (X) and Labels (y)
    X = df[['Bi_Encoder_Cosine', 'Cross_Encoder_Logit']]
    y = df['LABEL_1_or_0']
    
    # 3. Train the Model
    # class_weight='balanced' ensures we don't bias towards 0s if there are more non-matches
    clf = LogisticRegression(class_weight='balanced') 
    clf.fit(X, y)
    
    # 4. Extract the mathematical weights
    w_cosine, w_logit = clf.coef_[0]
    bias = clf.intercept_[0]
    
    print("\n✅ Training Complete. Insert these weights into services/reranker.py:")
    print("-" * 50)
    print(f"W_COSINE = {w_cosine:.4f}")
    print(f"W_LOGIT  = {w_logit:.4f}")
    print(f"BIAS     = {bias:.4f}")
    print("-" * 50)
    
    # 5. Quick Sanity Check
    def predict(cosine, logit):
        z = (w_cosine * cosine) + (w_logit * logit) + bias
        return 1 / (1 + np.exp(-z))
        
    print("\n🧪 Sanity Check:")
    print(f"Perfect Match (Cos 0.85, Logit 8.6) -> {predict(0.85, 8.6)*100:.1f}% Probability")
    print(f"Terrible Match (Cos 0.60, Logit -11) -> {predict(0.60, -11)*100:.1f}% Probability")

if __name__ == "__main__":
    train_model()