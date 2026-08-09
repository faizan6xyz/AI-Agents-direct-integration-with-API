import matplotlib
matplotlib.use('QtAgg') # this is impoortant for the linus user cause telling linux which GUIBACK to use 
import matplotlib.pyplot as plt
import numpy as np
data = np.random.randn(100)
plt.plot(data)
plt.title("Random Numbers Plot")
plt.xlabel("Index")
plt.ylabel("Value")
plt.show()

