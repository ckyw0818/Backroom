from ursina import *

app = Ursina()

e = Entity(model='cube', color=color.orange, scale=2)
EditorCamera()

app.run()