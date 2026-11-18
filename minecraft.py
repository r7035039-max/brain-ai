"""Brain AI Minecraft-style voxel sandbox. Requires: pip install ursina"""
from ursina import *
from ursina.prefabs.first_person_controller import FirstPersonController
import random, math, json, os

app = Ursina()
window.title = 'BrainCraft — Brain AI v2'
window.borderless = False
window.fps_counter.enabled = True
window.exit_button.visible = False

BLOCKS = {'grass': color.rgb(90, 165, 75), 'dirt': color.rgb(125, 91, 61),
          'stone': color.rgb(135, 140, 147), 'wood': color.rgb(134, 94, 52),
          'sand': color.rgb(213, 194, 135)}
block_names = list(BLOCKS)
selected = 0
world = {}
SAVE = os.path.join(os.path.dirname(__file__), 'braincraft_world.json')

class Voxel(Button):
    def __init__(self, position, block='grass'):
        super().__init__(parent=scene, position=position, model='cube',
                         origin_y=.5, texture='white_cube', color=BLOCKS[block],
                         highlight_color=color.rgba(255,255,255,80), collider='box')
        self.block = block

def put(pos, block):
    pos = tuple(int(x) for x in pos)
    if pos in world: destroy(world[pos])
    world[pos] = Voxel(pos, block)

def remove(pos):
    pos = tuple(int(x) for x in pos)
    if pos in world: destroy(world.pop(pos))

def make_world():
    random.seed(42)
    for x in range(-12, 13):
        for z in range(-12, 13):
            height = int(1.5 * math.sin(x*.24) + 1.2 * math.cos(z*.29))
            for y in range(-3, height + 1):
                if y == height: block = 'sand' if height < 0 else 'grass'
                elif y > height - 3: block = 'dirt'
                else: block = 'stone'
                put((x,y,z),block)
    for x,z in [(-7,-5),(7,6),(4,-8)]:
        top = max(y for xx,y,zz in world if xx == x and zz == z)
        for y in range(top+1,top+5): put((x,y,z),'wood')

def save_world():
    with open(SAVE,'w',encoding='utf-8') as f:
        json.dump([[*p, v.block] for p,v in world.items()],f)
    status.text = 'World saved (F5)'

def load_world():
    if not os.path.isfile(SAVE): return False
    with open(SAVE,encoding='utf-8') as f: blocks=json.load(f)
    for v in list(world.values()): destroy(v)
    world.clear()
    for x,y,z,b in blocks:
        if b in BLOCKS: put((x,y,z),b)
    return True

if not load_world(): make_world()
player = FirstPersonController(position=(0,8,0), speed=6, jump_height=1.6)
player.cursor.color = color.white
Sky(color=color.rgb(130,190,245))
DirectionalLight(rotation=(35,-35,0), shadows=False)
AmbientLight(color=color.rgba(160,160,160,255))
help_text = Text(text='WASD move | Mouse look | Space jump | Left break | Right place | 1-5 blocks | F5 save | ESC mouse',
                 position=(-.86,.46),scale=.85,background=True)
status = Text(text='Block: grass',position=(-.86,.41),scale=1.1)

def input(key):
    global selected
    if key in ['1','2','3','4','5']:
        selected = int(key)-1
        status.text = 'Block: ' + block_names[selected]
    elif key == 'f5': save_world()
    elif key == 'escape': mouse.locked = not mouse.locked
    elif key in ('left mouse down','right mouse down'):
        hit = raycast(camera.world_position, camera.forward, distance=6, ignore=(player,))
        if hit.hit and isinstance(hit.entity,Voxel):
            p = hit.entity.position
            if key == 'left mouse down': remove((p.x,p.y,p.z))
            else:
                q = p + hit.normal
                if distance(q,player.position)>1.5: put((round(q.x),round(q.y),round(q.z)),block_names[selected])

app.run()
