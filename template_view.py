"""Pygame renderer for Brain AI's three editable game foundations."""
import json
import math
import os
from pathlib import Path
os.environ.setdefault('PYGAME_HIDE_SUPPORT_PROMPT', '1')
import pygame
from game_core import Game


def main():
    config = json.loads(Path(__file__).with_name('level.json').read_text(encoding='utf-8'))
    game = Game(config)
    pygame.init()
    screen = pygame.display.set_mode((960, 620))
    pygame.display.set_caption(config.get('title', 'Brain Arcade'))
    font = pygame.font.Font(None, 27)
    big = pygame.font.Font(None, 66)
    clock = pygame.time.Clock()
    playing, running = False, True
    colors = {'gold': '#ffc86a', 'stone': '#7d9ec4', 'grass': '#72cfac'}
    def text(value, position, color='#e8eef9', title=False):
        screen.blit((big if title else font).render(str(value), True, color), position)
    def project_point(x, y, z):
        dx, dz = x - game.x, z - game.z
        xx = dx * math.cos(game.yaw) - dz * math.sin(game.yaw)
        zz = dx * math.sin(game.yaw) + dz * math.cos(game.yaw)
        if zz <= .12:
            return None
        return (int(480 + xx * 420 / zz), int(310 - (y - game.y - 1.4) * 420 / zz))
    while running:
        dt = min(clock.tick(60) / 1000, .05)
        look, breaking, placing = 0, False, False
        for event in pygame.event.get():
            if event.type == pygame.QUIT: running = False
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    playing = False
                    pygame.event.set_grab(False)
                    pygame.mouse.set_visible(True)
                if event.key in (pygame.K_RETURN, pygame.K_r):
                    game.reset()
                    playing = True
            if event.type == pygame.MOUSEBUTTONDOWN:
                if (not playing or game.won or not game.alive) and 330 < event.pos[0] < 630 and 310 < event.pos[1] < 380:
                    playing = True
                    game.reset()
                elif playing:
                    breaking, placing = event.button == 1, event.button == 3
            if event.type == pygame.MOUSEMOTION and playing and game.kind == 'voxel':
                if pygame.event.get_grab(): look += event.rel[0] * .004
            if event.type == pygame.KEYDOWN and event.key == pygame.K_TAB and game.kind == 'voxel':
                pygame.event.set_grab(not pygame.event.get_grab())
                pygame.mouse.set_visible(not pygame.event.get_grab())
        keys = pygame.key.get_pressed()
        if playing:
            game.step({'left': keys[pygame.K_a] or keys[pygame.K_LEFT], 'right': keys[pygame.K_d] or keys[pygame.K_RIGHT],
                       'forward': keys[pygame.K_w] or keys[pygame.K_UP], 'back': keys[pygame.K_s] or keys[pygame.K_DOWN],
                       'jump': keys[pygame.K_SPACE], 'look': look, 'break': breaking or keys[pygame.K_e],
                       'place': placing or keys[pygame.K_q]}, dt)
        screen.fill('#111a2b')
        if game.kind == 'platformer':
            scale, camera = 36, max(-2, game.x - 9)
            for i in range(11):
                pygame.draw.line(screen, '#1b2940', (0, i * 62), (960, i * 62))
            for i in range(-4, int(game.finish) + 8):
                if not any(a <= i + .5 <= b for a, b in game.pits):
                    pygame.draw.rect(screen, '#2a665b', ((i - camera) * scale, 530, scale + 1, 90))
            for x, y, w, h in game.walls:
                pygame.draw.rect(screen, '#5776a0', ((x - camera) * scale, 530 - (y + h) * scale, w * scale, h * scale), border_radius=5)
            for x in game.hazards:
                pygame.draw.polygon(screen, '#f17d8a', [((x - camera) * scale - 16, 530), ((x - camera) * scale, 502), ((x - camera) * scale + 16, 530)])
            for x in game.coins:
                pygame.draw.circle(screen, '#ffc86a', (int((x - camera) * scale), 480), 8)
            fx = int((game.finish - camera) * scale)
            pygame.draw.line(screen, '#f4f7ff', (fx, 450), (fx, 530), 3)
            pygame.draw.polygon(screen, '#73e0ad', [(fx, 450), (fx + 32, 462), (fx, 475)])
            pygame.draw.rect(screen, '#83b6ff', ((game.x - camera - .3) * scale, 530 - (game.y + 1) * scale, .6 * scale, scale), border_radius=6)
        elif game.kind == 'racing':
            screen.fill('#111b34')
            pygame.draw.circle(screen, '#dd7199', (480, 180), 75)
            pygame.draw.polygon(screen, '#252b42', [(0, 620), (390, 200), (570, 200), (960, 620)])
            for side in [-1, 1]:
                pygame.draw.line(screen, '#76d2ca', (480 + side * 88, 200), (480 + side * 470, 620), 5)
            for i in range(18):
                depth = ((i * 5 - game.z) % 90) / 90
                y = 205 + depth * depth * 415
                for lane in [-1, 1]: pygame.draw.line(screen, '#d1caed', (480 + lane * depth * 145, y), (480 + lane * depth * 145, y + 8 + depth * 18), 3)
            for x, z in game.obstacles:
                ahead = z - game.z
                if 0 < ahead < 60:
                    scale = 3 / (ahead + 3)
                    pygame.draw.rect(screen, '#f29a76', (480 + x * 150 * scale - 30 * scale, 210 + 360 * scale, 60 * scale, 80 * scale), border_radius=3)
            pygame.draw.rect(screen, '#72e1cf', (440 + game.x * 130, 500 - game.y * 35, 80, 90), border_radius=14)
            pygame.draw.rect(screen, '#152335', (454 + game.x * 130, 515 - game.y * 35, 52, 22), border_radius=6)
        else:
            screen.fill('#293957')
            pygame.draw.rect(screen, '#253e3e', (0, 310, 960, 310))
            faces = []
            for (x, y, z), material in game.blocks.items():
                corners = [(x + dx, y + dy, z + dz) for dx, dy, dz in [(0,0,0),(1,0,0),(1,1,0),(0,1,0),(0,0,1),(1,0,1),(1,1,1),(0,1,1)]]
                for face in [(0,1,2,3),(4,5,6,7),(0,4,7,3),(1,5,6,2),(3,2,6,7)]:
                    points = [project_point(*corners[index]) for index in face]
                    if all(points):
                        distance = sum((corners[index][0] - game.x)**2 + (corners[index][2] - game.z)**2 for index in face)
                        faces.append((distance, points, colors.get(material, '#7d9ec4')))
            for _, points, color in sorted(faces, reverse=True):
                pygame.draw.polygon(screen, color, points)
                pygame.draw.polygon(screen, '#243242', points, 2)
            pygame.draw.line(screen, '#ffffff', (470,310), (490,310), 2)
            pygame.draw.line(screen, '#ffffff', (480,300), (480,320), 2)
        text(config.get('title', 'Brain Arcade'), (26, 18))
        text(f'SCORE {game.score}   TIME {game.elapsed:.1f}', (26, 52), '#b3c7e4')
        text('A/D move • SPACE jump • W accelerate/walk • R restart • ESC menu', (22, 590), '#9db3d2')
        if game.kind == 'voxel': text('TAB mouse look • E break gold • Q place blocks', (22, 558), '#ffc86a')
        if not playing or not game.alive or game.won:
            shade = pygame.Surface((960,620), pygame.SRCALPHA)
            shade.fill((7, 12, 24, 205))
            screen.blit(shade, (0,0))
            text('YOU WIN' if game.won else 'TRY AGAIN' if not game.alive else config.get('title', 'Brain Arcade'), (90, 180), title=True)
            text(config.get('description', 'A small game built in Brain AI'), (90, 260), '#a9bdd8')
            pygame.draw.rect(screen, '#75ddbd', (330,310,300,70), border_radius=14)
            text('PLAY / RESTART  [ENTER]', (357,331), '#10232c')
            text('Collect gold' if game.kind == 'voxel' else 'Reach the finish. Avoid the hazards.', (90, 430))
        pygame.display.flip()
    pygame.quit()

if __name__ == '__main__':
    main()
