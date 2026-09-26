import numpy as np


def measure(gray):
    return {"exposure": float(gray.mean()), "luminancePercentiles": np.percentile(gray, [1, 10, 50, 90, 99]).tolist(),
            "highlightClipping": float(np.mean(gray >= 250)), "shadowClipping": float(np.mean(gray <= 5))}
