import sys
from fusion import make_intro_frame
from PIL import Image

title = sys.argv[1] if len(sys.argv) > 1 else 'OPAL EPISODE'
img = Image.fromarray(make_intro_frame(7.0, title))
img.save('intro_test.png')
print(f'Saved intro_test.png for: {title}')
