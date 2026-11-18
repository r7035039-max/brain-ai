"""Pure Python game rules shared by rendering and deterministic gameplay tests."""
import math

class Game:
    def __init__(self, config=None):
        self.config = dict(config or {})
        self.kind = self.config.get('kind', 'platformer')
        self.reset()

    def reset(self, seed=0):
        self.x = self.y = self.z = self.vy = self.yaw = self.elapsed = 0.0
        self.alive, self.won, self.grounded = True, False, True
        self.collisions = self.score = 0
        self.jump_down = self.break_down = self.place_down = False
        self.finish = float(self.config.get('finish', 28 if self.kind == 'platformer' else 160))
        self.hazards = list(self.config.get('hazards', [9, 18]))
        self.walls = list(self.config.get('walls', [[5, 0, 1, 1.5], [15, 0, 1, 1.7]]))
        self.pits = list(self.config.get('pits', [[11, 12.5], [21, 22.5]]))
        self.obstacles = list(self.config.get('obstacles', [[0, 28], [-1.7, 60], [1.5, 94], [0, 130]]))
        self.coins = set(float(x) for x in self.config.get('coins', [3, 7, 13, 17, 24]))
        default = [[x, 0, z, 'stone'] for x, z in [(-3, 3), (3, 5), (-2, 7), (3, 9)]]
        default += [[x, 1, z, 'gold'] for x, z in [(0, 3), (2, 5), (-2, 6), (0, 8)]]
        self.blocks = {(int(x), int(y), int(z)): str(color) for x, y, z, color in self.config.get('blocks', default)}
        self.goal = int(self.config.get('gold_goal', 4))

    def configure_test(self, case):
        self.reset()
        self.hazards, self.walls, self.pits, self.obstacles = [], [], [], []
        self.finish = 1000
        self.blocks = {}
        if case == 'collision':
            self.walls = [[1.5, 0, 1, 3]]
            self.blocks = {(1, 0, 0): 'stone', (1, 1, 0): 'stone'}
        elif case == 'win':
            self.finish = 2
            self.goal = 1
            self.blocks = {(0, 1, 2): 'gold'}
        elif case == 'lose':
            self.hazards = [1.5]
            self.obstacles = [[0, 1.5]]
            if self.kind == 'voxel':
                self.x, self.y, self.grounded = 12, 0, False

    def snapshot(self):
        return {'kind': self.kind, 'x': self.x, 'y': self.y, 'z': self.z, 'alive': self.alive,
                'won': self.won, 'grounded': self.grounded, 'collisions': self.collisions,
                'score': self.score, 'elapsed': self.elapsed}

    def ray(self):
        previous = None
        for i in range(1, 51):
            t = i / 10
            point = (math.floor(self.x + math.sin(self.yaw) * t), math.floor(self.y + 1.4),
                     math.floor(self.z + math.cos(self.yaw) * t))
            if point in self.blocks:
                return point, previous
            previous = point
        return None, previous

    def step(self, controls, dt=1/60):
        dt = max(0.0, min(float(dt), 0.05))
        if not self.alive or self.won:
            return self.snapshot()
        self.elapsed += dt
        direction = int(bool(controls.get('right'))) - int(bool(controls.get('left')))
        jump = bool(controls.get('jump'))
        if jump and not self.jump_down and self.grounded:
            self.vy, self.grounded = float(self.config.get('jump_speed', 9.5)), False
        self.jump_down = jump
        old_y = self.y
        self.vy -= float(self.config.get('gravity', 20)) * dt
        self.y += self.vy * dt
        floor = 0.0
        if self.kind == 'platformer':
            old_x = self.x
            self.x += direction * float(self.config.get('speed', 4.5)) * dt
            for wx, wy, width, height in self.walls:
                if self.x + .3 > wx and self.x - .3 < wx + width:
                    top = wy + height
                    if old_y >= top and self.y <= top:
                        floor = max(floor, top)
                    elif self.y < top and self.y + 1 > wy:
                        self.x = wx - .3 if old_x < wx else wx + width + .3
                        self.collisions += 1
            if any(a < self.x < b for a, b in self.pits) or self.x < -3:
                floor = -100
            if any(abs(self.x - h) < .55 and self.y < .7 for h in self.hazards):
                self.alive = False
            for coin in list(self.coins):
                if abs(self.x - coin) < .5 and self.y < 2.5:
                    self.coins.remove(coin)
                    self.score += 1
            self.won = self.alive and self.x >= self.finish
        elif self.kind == 'racing':
            self.x += direction * 3.5 * dt
            self.z += (18 if controls.get('forward') else 8) * dt
            if abs(self.x) > 2.6:
                self.x = max(-2.6, min(2.6, self.x))
                self.collisions += 1
            if any(abs(self.x - x) < .7 and abs(self.z - z) < .8 and self.y < .75 for x, z in self.obstacles):
                self.alive = False
                self.collisions += 1
            self.won = self.alive and self.z >= self.finish
            self.score = int(self.z)
        else:
            self.yaw += float(controls.get('look', 0))
            forward = int(bool(controls.get('forward'))) - int(bool(controls.get('back')))
            dx = (math.sin(self.yaw) * forward + math.cos(self.yaw) * direction) * 3.2 * dt
            dz = (math.cos(self.yaw) * forward - math.sin(self.yaw) * direction) * 3.2 * dt
            for axis, change in [('x', dx), ('z', dz)]:
                old = getattr(self, axis)
                setattr(self, axis, old + change)
                if any(x - .25 < self.x < x + 1.25 and z - .25 < self.z < z + 1.25
                       and y < self.y + 1.7 and y + 1 > self.y + .05 for x, y, z in self.blocks):
                    setattr(self, axis, old)
                    self.collisions += 1
            for bx, by, bz in self.blocks:
                if (bx - .25 < self.x < bx + 1.25 and bz - .25 < self.z < bz + 1.25
                        and old_y >= by + 1 and self.y <= by + 1):
                    floor = max(floor, by + 1)
            target, empty = self.ray()
            breaking, placing = bool(controls.get('break')), bool(controls.get('place'))
            if breaking and not self.break_down and target:
                self.score += self.blocks.pop(target) == 'gold'
            if placing and not self.place_down and target and empty:
                if abs(empty[0] + .5 - self.x) > .8 or abs(empty[2] + .5 - self.z) > .8:
                    self.blocks[empty] = 'stone'
            self.break_down, self.place_down = breaking, placing
            if abs(self.x) > 10 or abs(self.z) > 10:
                floor = -100
            self.won = self.score >= self.goal
        self.grounded = self.y <= floor and self.vy <= 0
        if self.grounded:
            self.y, self.vy = floor, 0
        if self.y < -5:
            self.alive = False
        return self.snapshot()
