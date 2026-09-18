import numpy as np
import matplotlib.pyplot as plt

# 1. Environment Dimensions (centimeters)
room_width = 883.0   
room_length = 516.0  
resolution = 10.0   

# 2. Create the Physical Fingerprinting Grid (100 cm spacing)
# Starting 40cm from the walls to avoid physical boundaries
grid_spacing = 100.0
fp_x = np.arange(40, room_width, grid_spacing)
fp_y = np.arange(40, room_length, grid_spacing)
FP_X, FP_Y = np.meshgrid(fp_x, fp_y)

# 3. Dynamic Sniffer Placement (Locked to the outermost grid corners)
# A1: Bottom-Left grid corner (Index 0)
# A2: Top-Right grid corner (Index -1 gets the last element in an array)
A1_pos = (fp_x[0], fp_y[0])
A2_pos = (fp_x[-1], fp_y[-1])

# Simulated Target (MDN Bounding Box Output)
target_mu_x = 333.0       
target_mu_y = 314.0       
target_variance = 60.0   # heatmap variance probability -- higher variance = lower confidence level/spatial uncertainty

# 4. Create Spatial Heatmap Grid & Probabilities
x = np.arange(0, room_width, resolution)
y = np.arange(0, room_length, resolution)
X, Y = np.meshgrid(x, y)

# MDN Output - simulating Gaussian probability
Z = np.exp(-(((X - target_mu_x)**2 / (2 * target_variance**2)) + 
             ((Y - target_mu_y)**2 / (2 * target_variance**2))))

# 5. Plot Heatmap
plt.figure(figsize=(11, 6))
heatmap = plt.imshow(Z, extent=[0, room_width, 0, room_length], origin='lower',
                     cmap='magma', alpha=0.9)
plt.colorbar(heatmap, label='Presence Probability')

# Overlay Fingerprint Grid
plt.scatter(FP_X, FP_Y, color='gray', marker='+', s=40, alpha=0.7, 
            label='Fingerprint Grid (RPs)')

# Overlay Sniffers 
# Sniffer A1
plt.scatter(*A1_pos, color='cyan', marker='o', s=220, edgecolors='black', linewidth=1.5, label='Sniffer A1')
plt.scatter(*A1_pos, color='black', marker='x', s=90, linewidth=2)

# Sniffer A2
plt.scatter(*A2_pos, color='lime', marker='o', s=220, edgecolors='black', linewidth=1.5, label='Sniffer A2')
plt.scatter(*A2_pos, color='black', marker='x', s=90, linewidth=2)

# Plot
plt.title('Fingerprint Map & Localization Heatmap')
plt.xlabel('Room Width (Centimeters)')
plt.ylabel('Room Length (Centimeters)')
plt.legend(bbox_to_anchor=(1.25, 1.0), loc='upper left', frameon=True)
plt.grid(color='white', linestyle='--', alpha=0.1)
plt.tight_layout()
plt.show()

