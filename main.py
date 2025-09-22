"""
Cartoon Survivor (pygame) — Champions & World (Obstacle + spawn + movement fixes)
- Fixes:
  * Obstacles won't form clusters larger than MAX_NEARBY_OBSTACLES.
  * Mobs won't spawn inside obstacles.
  * Mobs attempt simple steering around obstacles instead of getting stuck.
- All other features (champions, lava pools, projectiles, camera) kept.
"""

import pygame
import random
import math
import sys
from dataclasses import dataclass, field
from typing import List, Tuple

# ----- Config -----
SCREEN_W, SCREEN_H = 800, 600
WORLD_W, WORLD_H = 2400, 1800  # larger map
PLAYER_RADIUS = 16
MOB_RADIUS = 14
LAVA_RADIUS = 60
LEVEL_DURATION_SECONDS = 10 * 60
FPS = 60

# Obstacles tuning
OBSTACLE_COUNT = 80
NEAR_RADIUS = 120           # radius to consider "nearby" for clustering
MAX_NEARBY_OBSTACLES = 2    # maximum obstacles allowed in a cluster
GRID_BIAS = 200             # bias placement toward grid spacing to spread them out
OBSTACLE_SAFETY_MARGIN = 8  # extra spacing when checking overlap

# Champion presets
CHAMPIONS = {
    'mage': {
        'name': 'Mage',
        'desc': 'Shoots fireballs (medium speed, high damage).',
        'attack_type': 'projectile',
        'proj_speed': 420,
        'proj_dmg': 28,
        'cooldown': 0.7,
        'range': 520,
    },
    'rogue': {
        'name': 'Rogue',
        'desc': 'Fires fast arrows (low damage, fast rate).',
        'attack_type': 'projectile',
        'proj_speed': 650,
        'proj_dmg': 14,
        'cooldown': 0.35,
        'range': 620,
    },
    'knight': {
        'name': 'Knight',
        'desc': 'Short-range melee sword (high damage).',
        'attack_type': 'melee',
        'proj_speed': 0,
        'proj_dmg': 36,
        'cooldown': 0.5,
        'range': 56,
    }
}

# Enemy types
ENEMY_TYPES = ['melee', 'shooter', 'lava']

# ----- Dataclasses -----
@dataclass
class Obstacle:
    rect: pygame.Rect
    kind: str  # for aesthetic (tree, rock, house, water, hay)

@dataclass
class Projectile:
    x: float
    y: float
    vx: float
    vy: float
    speed: float
    dmg: float
    owner: str  # 'player' or 'mob'
    ttl: float = 6.0

@dataclass
class LavaPool:
    x: float
    y: float
    radius: float
    duration: float
    tick: float = 0.0

@dataclass
class Mob:
    x: float
    y: float
    hp: float
    speed: float
    type: str
    cooldown: float = 0.0
    id: int = field(default_factory=lambda: random.randint(0, 999999))

@dataclass
class Player:
    x: float
    y: float
    hp: float = 100
    level: int = 1
    xp: int = 0
    speed: float = 250.0
    attack_cooldown: float = 0.5
    attack_timer: float = 0.0
    champion: str = 'mage'
    proj_speed: float = 420
    proj_dmg: float = 20
    attack_range: float = 520
    attack_type: str = 'projectile'

# ----- Helpers -----

def clamp(v, a, b):
    return max(a, min(b, v))


def distance(ax, ay, bx, by):
    return math.hypot(ax - bx, ay - by)


def circle_rect_collision(cx, cy, r, rect: pygame.Rect):
    # closest point
    closest_x = clamp(cx, rect.left, rect.right)
    closest_y = clamp(cy, rect.top, rect.bottom)
    return distance(cx, cy, closest_x, closest_y) <= r

# ----- Spawning & World -----

def spawn_mob(minute: int, player_x: float, player_y: float, obstacles: List[Obstacle]) -> Mob:
    """
    Spawn a mob at a safe location:
     - not too near the player
     - not inside or too close to obstacles
    """
    tries = 0
    while True:
        # grid biased sampling (keeps things distributed)
        gx = random.randint(0, WORLD_W // GRID_BIAS if WORLD_W // GRID_BIAS > 0 else 1)
        gy = random.randint(0, WORLD_H // GRID_BIAS if WORLD_H // GRID_BIAS > 0 else 1)
        x = gx * GRID_BIAS + random.uniform(-GRID_BIAS/2, GRID_BIAS/2)
        y = gy * GRID_BIAS + random.uniform(-GRID_BIAS/2, GRID_BIAS/2)
        x = clamp(x, 0, WORLD_W)
        y = clamp(y, 0, WORLD_H)

        # safety: not too near player spawn/position
        if distance(x, y, player_x, player_y) < 300:
            tries += 1
            if tries > 300:
                # fallback random
                x = random.uniform(0, WORLD_W)
                y = random.uniform(0, WORLD_H)
                break
            continue

        # ensure not inside obstacles and not too close to obstacle edges
        inside_obs = False
        for o in obstacles:
            # use inflated rect for safety margin
            if o.rect.inflate(OBSTACLE_SAFETY_MARGIN * 2, OBSTACLE_SAFETY_MARGIN * 2).collidepoint(x, y):
                inside_obs = True
                break
        if inside_obs:
            tries += 1
            if tries > 500:
                # fallback random
                x = random.uniform(0, WORLD_W)
                y = random.uniform(0, WORLD_H)
                break
            continue

        # all good
        break

    t = random.choices(ENEMY_TYPES, weights=[0.6, 0.25, 0.15])[0]
    base_hp = 22
    hp = base_hp + minute * 15 + random.uniform(-4, 6)
    base_speed = 55
    speed = base_speed + minute * 8 + random.uniform(-8, 8)
    cooldown = random.uniform(0.8, 2.2)
    return Mob(x=x, y=y, hp=hp, speed=speed, type=t, cooldown=cooldown)

# Obstacles generator (improved)
def generate_obstacles(count=OBSTACLE_COUNT) -> List[Obstacle]:
    """
    Place obstacles with these constraints:
      - avoid the central spawn area
      - grid-biased candidate points to spread them
      - no more than MAX_NEARBY_OBSTACLES in any NEAR_RADIUS cluster (post-process)
      - avoid overlap (with small margin)
    """
    obs: List[Obstacle] = []
    kinds = ['tree', 'rock', 'house', 'water', 'hay']

    # build grid-biased candidate centers
    candidates = []
    x_cells = max(4, WORLD_W // GRID_BIAS)
    y_cells = max(4, WORLD_H // GRID_BIAS)
    for gx in range(x_cells):
        for gy in range(y_cells):
            cx = int((gx + 0.5) * WORLD_W / x_cells + random.uniform(-GRID_BIAS/3, GRID_BIAS/3))
            cy = int((gy + 0.5) * WORLD_H / y_cells + random.uniform(-GRID_BIAS/3, GRID_BIAS/3))
            candidates.append((cx, cy))
    random.shuffle(candidates)

    tries = 0
    max_tries = len(candidates) * 6
    center_area = pygame.Rect(WORLD_W // 2 - 400, WORLD_H // 2 - 300, 800, 600)

    for (cx, cy) in candidates:
        if len(obs) >= count or tries >= max_tries:
            break
        # randomize size
        w = random.randint(40, 160)
        h = random.randint(40, 140)
        x = clamp(cx + random.randint(-GRID_BIAS//2, GRID_BIAS//2), 0, WORLD_W - w)
        y = clamp(cy + random.randint(-GRID_BIAS//2, GRID_BIAS//2), 0, WORLD_H - h)
        rect = pygame.Rect(x, y, w, h)
        tries += 1

        # avoid center spawn area
        if rect.colliderect(center_area):
            continue

        # ensure not overlapping (allow some spacing)
        overlapped = False
        for o in obs:
            if rect.inflate(OBSTACLE_SAFETY_MARGIN * 2, OBSTACLE_SAFETY_MARGIN * 2).colliderect(o.rect):
                overlapped = True
                break
        if overlapped:
            continue

        # count nearby obstacles by center distance
        nearby = 0
        for o in obs:
            if distance(o.rect.centerx, o.rect.centery, rect.centerx, rect.centery) < NEAR_RADIUS:
                nearby += 1
                if nearby >= MAX_NEARBY_OBSTACLES:
                    break
        if nearby >= MAX_NEARBY_OBSTACLES:
            continue

        obs.append(Obstacle(rect, random.choice(kinds)))

    # If we didn't reach target count, try random placement with same checks
    extra_tries = 0
    while len(obs) < count and extra_tries < count * 12:
        w = random.randint(40, 140)
        h = random.randint(40, 120)
        x = random.randint(0, WORLD_W - w)
        y = random.randint(0, WORLD_H - h)
        rect = pygame.Rect(x, y, w, h)
        if rect.colliderect(center_area):
            extra_tries += 1; continue
        overlapped = any(rect.inflate(OBSTACLE_SAFETY_MARGIN * 2, OBSTACLE_SAFETY_MARGIN * 2).colliderect(o.rect) for o in obs)
        if overlapped:
            extra_tries += 1; continue
        nearby = sum(1 for o in obs if distance(o.rect.centerx, o.rect.centery, rect.centerx, rect.centery) < NEAR_RADIUS)
        if nearby >= MAX_NEARBY_OBSTACLES:
            extra_tries += 1; continue
        obs.append(Obstacle(rect, random.choice(kinds)))
        extra_tries += 1

    # POST-PROCESS: ensure there are no clusters bigger than MAX_NEARBY_OBSTACLES
    # Build adjacency by NEAR_RADIUS and prune components bigger than allowed.
    def build_adj_list(ob_list):
        n = len(ob_list)
        adj = [[] for _ in range(n)]
        for i in range(n):
            for j in range(i + 1, n):
                if distance(ob_list[i].rect.centerx, ob_list[i].rect.centery,
                            ob_list[j].rect.centerx, ob_list[j].rect.centery) < NEAR_RADIUS:
                    adj[i].append(j)
                    adj[j].append(i)
        return adj

    def connected_components(adj):
        visited = [False] * len(adj)
        comps = []
        for i in range(len(adj)):
            if not visited[i]:
                stack = [i]
                comp = []
                visited[i] = True
                while stack:
                    u = stack.pop()
                    comp.append(u)
                    for v in adj[u]:
                        if not visited[v]:
                            visited[v] = True
                            stack.append(v)
                comps.append(comp)
        return comps

    adj = build_adj_list(obs)
    comps = connected_components(adj)
    # If any component bigger than MAX_NEARBY_OBSTACLES, remove random obstacles until size is ok
    to_remove_indices = set()
    for comp in comps:
        if len(comp) > MAX_NEARBY_OBSTACLES:
            # sort by degree (remove highest-degree or random) - remove until size satisfied
            comp_sorted = sorted(comp, key=lambda idx: len(adj[idx]), reverse=True)
            remove_needed = len(comp) - MAX_NEARBY_OBSTACLES
            for r in comp_sorted[:remove_needed]:
                to_remove_indices.add(r)

    if to_remove_indices:
        obs = [o for idx, o in enumerate(obs) if idx not in to_remove_indices]

    return obs

# ----- Main Game -----

def main():
    pygame.init()
    screen = pygame.display.set_mode((SCREEN_W, SCREEN_H))
    pygame.display.set_caption('Cartoon Survivor — Champions & World (Obstacle Fix v2)')
    clock = pygame.time.Clock()

    font = pygame.font.SysFont(None, 22)
    big = pygame.font.SysFont(None, 40)
    title_font = pygame.font.SysFont(None, 28)

    # Prepare world
    player = Player(x=WORLD_W // 2, y=WORLD_H // 2)
    projectile_list: List[Projectile] = []
    lava_pools: List[LavaPool] = []
    mobs: List[Mob] = []
    obstacles = generate_obstacles(OBSTACLE_COUNT)

    elapsed = 0.0
    spawn_acc = 0.0
    BASE_SPAWN = 1.7

    # Game states
    state = 'champ_select'  # 'playing', 'levelup', 'win', 'dead'

    # Camera
    cam_x, cam_y = 0.0, 0.0

    def world_to_screen(wx, wy):
        return wx - cam_x, wy - cam_y

    def screen_to_world(sx, sy):
        return sx + cam_x, sy + cam_y

    # Champion select menu
    def champion_menu():
        nonlocal state, player
        while state == 'champ_select':
            dt = clock.tick(FPS) / 1000.0
            for ev in pygame.event.get():
                if ev.type == pygame.QUIT:
                    pygame.quit(); sys.exit()
                if ev.type == pygame.KEYDOWN:
                    if ev.key == pygame.K_1:
                        choose_champion('mage'); return
                    if ev.key == pygame.K_2:
                        choose_champion('rogue'); return
                    if ev.key == pygame.K_3:
                        choose_champion('knight'); return
                if ev.type == pygame.MOUSEBUTTONDOWN:
                    mx, my = ev.pos
                    if mx < SCREEN_W / 3:
                        choose_champion('mage'); return
                    elif mx < 2 * SCREEN_W / 3:
                        choose_champion('rogue'); return
                    else:
                        choose_champion('knight'); return

            screen.fill((30, 40, 70))
            title = big.render('Choose your Champion', True, (255, 220, 170))
            screen.blit(title, (SCREEN_W // 2 - title.get_width() // 2, 30))

            # draw three cards
            for i, key in enumerate(['mage', 'rogue', 'knight']):
                cx = int((i + 0.5) * SCREEN_W / 3)
                cy = 180
                pygame.draw.rect(screen, (20, 20, 30), (cx - 140, cy - 90, 280, 180), border_radius=8)
                name = title_font.render(CHAMPIONS[key]['name'], True, (240, 240, 240))
                screen.blit(name, (cx - name.get_width() // 2, cy - 64))
                desc = font.render(CHAMPIONS[key]['desc'], True, (200, 200, 200))
                screen.blit(desc, (cx - desc.get_width() // 2, cy - 24))
                hint = font.render(f'Press {i+1} or click to select', True, (180, 180, 180))
                screen.blit(hint, (cx - hint.get_width() // 2, cy + 36))

            pygame.display.flip()

    def choose_champion(key):
        nonlocal player, state
        p = CHAMPIONS[key]
        player.champion = key
        player.attack_cooldown = p['cooldown']
        player.proj_speed = p['proj_speed']
        player.proj_dmg = p['proj_dmg']
        player.attack_range = p['range']
        player.attack_type = p['attack_type']
        state = 'playing'

    champion_menu()

    # Game loop
    running = True
    while running:
        dt = clock.tick(FPS) / 1000.0
        elapsed += dt
        minute = int(elapsed // 60)

        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                running = False
            if ev.type == pygame.KEYDOWN:
                if ev.key == pygame.K_ESCAPE:
                    running = False
                if state == 'levelup' and ev.key in (pygame.K_1, pygame.K_2, pygame.K_3):
                    # level choices
                    if ev.key == pygame.K_1:
                        # damage
                        player.proj_dmg += 8 + player.level * 2
                        player.attack_range += 10
                    elif ev.key == pygame.K_2:
                        # speed
                        player.speed += 40
                    elif ev.key == pygame.K_3:
                        # hp
                        player.hp += 40
                    state = 'playing'
                    player.level += 0  # already incremented when offered

        if state == 'playing':
            # input
            keys = pygame.key.get_pressed()
            dx = (keys[pygame.K_RIGHT] or keys[pygame.K_d]) - (keys[pygame.K_LEFT] or keys[pygame.K_a])
            dy = (keys[pygame.K_DOWN] or keys[pygame.K_s]) - (keys[pygame.K_UP] or keys[pygame.K_w])
            if dx != 0 or dy != 0:
                ln = math.hypot(dx, dy)
                dx /= ln; dy /= ln
                new_x = player.x + dx * player.speed * dt
                new_y = player.y + dy * player.speed * dt
                # collision with obstacles
                can_move = True
                for o in obstacles:
                    if circle_rect_collision(new_x, new_y, PLAYER_RADIUS, o.rect):
                        can_move = False
                        break
                if can_move:
                    player.x = clamp(new_x, 0, WORLD_W)
                    player.y = clamp(new_y, 0, WORLD_H)

            # camera centers on player but constrained to world bounds
            cam_x = clamp(player.x - SCREEN_W / 2, 0, WORLD_W - SCREEN_W)
            cam_y = clamp(player.y - SCREEN_H / 2, 0, WORLD_H - SCREEN_H)

            # spawn mobs (pass obstacles so spawn avoids them)
            spawn_interval = max(0.4, BASE_SPAWN - minute * 0.12)
            spawn_acc += dt
            while spawn_acc >= spawn_interval:
                spawn_acc -= spawn_interval
                mobs.append(spawn_mob(minute, player.x, player.y, obstacles))

            # update mobs
            for mob in mobs[:]:
                mob.cooldown = max(0.0, mob.cooldown - dt)
                if mob.type == 'melee':
                    # move toward player with obstacle avoidance (steering)
                    vx = player.x - mob.x
                    vy = player.y - mob.y
                    dist = math.hypot(vx, vy) or 1.0
                    vx /= dist; vy /= dist

                    # try direct step; if blocked, try angled offsets
                    step = mob.speed * dt
                    moved = False

                    def try_move_with_vector(dx_unit, dy_unit):
                        nx = mob.x + dx_unit * step
                        ny = mob.y + dy_unit * step
                        # check obstacle collision
                        for o in obstacles:
                            if circle_rect_collision(nx, ny, MOB_RADIUS, o.rect):
                                return False, None, None
                        return True, nx, ny

                    # angles to try (in radians)
                    angles = [0, math.radians(30), math.radians(-30), math.radians(60), math.radians(-60), math.radians(100), math.radians(-100)]
                    for ang in angles:
                        ca = math.cos(ang); sa = math.sin(ang)
                        dx_try = vx * ca - vy * sa
                        dy_try = vx * sa + vy * ca
                        ok, nx, ny = try_move_with_vector(dx_try, dy_try)
                        if ok:
                            mob.x = clamp(nx, 0, WORLD_W)
                            mob.y = clamp(ny, 0, WORLD_H)
                            moved = True
                            break

                    # if couldn't move, remain (avoids tunneling into obstacle)
                    # contact damage
                    if distance(mob.x, mob.y, player.x, player.y) <= MOB_RADIUS + PLAYER_RADIUS:
                        player.hp -= 12 * dt

                elif mob.type == 'shooter':
                    # keep distance: back up if too close, approach if far (with steering)
                    vx = player.x - mob.x
                    vy = player.y - mob.y
                    dist = math.hypot(vx, vy) or 1.0
                    vx /= dist; vy /= dist
                    desired = 380

                    def attempt_translate(dx_unit, dy_unit, speed_mult=1.0):
                        nx = mob.x + dx_unit * mob.speed * speed_mult * dt
                        ny = mob.y + dy_unit * mob.speed * speed_mult * dt
                        for o in obstacles:
                            if circle_rect_collision(nx, ny, MOB_RADIUS, o.rect):
                                return False, None, None
                        return True, nx, ny

                    if dist > desired:
                        # approach using steering
                        moved = False
                        angles = [0, math.radians(25), math.radians(-25), math.radians(50), math.radians(-50)]
                        for ang in angles:
                            ca = math.cos(ang); sa = math.sin(ang)
                            dx_try = vx * ca - vy * sa
                            dy_try = vx * sa + vy * ca
                            ok, nx, ny = attempt_translate(dx_try, dy_try)
                            if ok:
                                mob.x = clamp(nx, 0, WORLD_W)
                                mob.y = clamp(ny, 0, WORLD_H)
                                moved = True
                                break
                    elif dist < desired - 60:
                        # back up
                        moved = False
                        for ang in [0, math.radians(25), math.radians(-25)]:
                            ca = math.cos(ang); sa = math.sin(ang)
                            dx_try = -vx * ca + vy * sa
                            dy_try = -vx * sa - vy * ca
                            ok, nx, ny = attempt_translate(dx_try, dy_try)
                            if ok:
                                mob.x = clamp(nx, 0, WORLD_W)
                                mob.y = clamp(ny, 0, WORLD_H)
                                moved = True
                                break

                    # shoot
                    if mob.cooldown <= 0 and dist <= 700:
                        dirx, diry = vx, vy
                        ps = 420
                        pvx = dirx * ps
                        pvy = diry * ps
                        projectile_list.append(Projectile(mob.x, mob.y, pvx, pvy, ps, dmg=18 + minute * 2, owner='mob'))
                        mob.cooldown = random.uniform(1.2, 2.0)

                elif mob.type == 'lava':
                    # wander slowly and occasionally drop lava pool
                    ang = random.uniform(0, math.tau)
                    nx = mob.x + math.cos(ang) * mob.speed * 0.25 * dt
                    ny = mob.y + math.sin(ang) * mob.speed * 0.25 * dt
                    # check collision before moving
                    blocked = False
                    for o in obstacles:
                        if circle_rect_collision(nx, ny, MOB_RADIUS, o.rect):
                            blocked = True
                            break
                    if not blocked:
                        mob.x = clamp(nx, 0, WORLD_W)
                        mob.y = clamp(ny, 0, WORLD_H)

                    if mob.cooldown <= 0:
                        lava_pools.append(LavaPool(mob.x, mob.y, LAVA_RADIUS, duration=6.0 + random.uniform(-1, 2)))
                        mob.cooldown = 4.0 + random.uniform(0, 3.0)

                # remove mob if dead
                if mob.hp <= 0:
                    try:
                        mobs.remove(mob)
                    except ValueError:
                        pass
                    player.xp += 1

            # update projectiles
            for p in projectile_list[:]:
                p.ttl -= dt
                p.x += p.vx * dt
                p.y += p.vy * dt
                # world collisions
                if p.ttl <= 0 or not (0 <= p.x <= WORLD_W and 0 <= p.y <= WORLD_H):
                    if p in projectile_list:
                        projectile_list.remove(p)
                    continue
                # hit obstacles (stop / disappear)
                hit_obs = False
                for o in obstacles:
                    if circle_rect_collision(p.x, p.y, 4, o.rect):
                        hit_obs = True
                        break
                if hit_obs:
                    if p in projectile_list:
                        projectile_list.remove(p)
                    continue
                # hit player
                if p.owner == 'mob' and distance(p.x, p.y, player.x, player.y) <= PLAYER_RADIUS + 6:
                    player.hp -= p.dmg
                    if p in projectile_list:
                        projectile_list.remove(p)
                    continue
                # hit mobs (player projectiles)
                if p.owner == 'player':
                    for mob in mobs[:]:
                        if distance(p.x, p.y, mob.x, mob.y) <= MOB_RADIUS + 6:
                            mob.hp -= p.dmg
                            if p in projectile_list:
                                projectile_list.remove(p)
                            break

            # update lava pools
            for lava in lava_pools[:]:
                lava.duration -= dt
                lava.tick += dt
                if lava.duration <= 0:
                    lava_pools.remove(lava)
                    continue
                # damage player if inside
                if distance(player.x, player.y, lava.x, lava.y) <= lava.radius:
                    player.hp -= 28 * dt

            # Player auto-attack by champion
            player.attack_timer -= dt
            if player.attack_timer <= 0:
                # find nearest mob in range
                if mobs:
                    nearest = min(mobs, key=lambda m: distance(player.x, player.y, m.x, m.y))
                    dist = distance(player.x, player.y, nearest.x, nearest.y)
                    if dist <= player.attack_range:
                        if player.attack_type == 'projectile':
                            # shoot one projectile at nearest
                            dx = (nearest.x - player.x) / (dist or 1)
                            dy = (nearest.y - player.y) / (dist or 1)
                            pvx = dx * player.proj_speed
                            pvy = dy * player.proj_speed
                            projectile_list.append(Projectile(player.x, player.y, pvx, pvy, player.proj_speed, player.proj_dmg, owner='player'))
                            player.attack_timer = player.attack_cooldown
                        else:  # melee
                            # damage mobs in melee range
                            for mob in mobs[:]:
                                if distance(player.x, player.y, mob.x, mob.y) <= player.attack_range + MOB_RADIUS:
                                    mob.hp -= player.proj_dmg
                            player.attack_timer = player.attack_cooldown

            # Level up check
            if player.xp >= player.level * 5:
                player.level += 1
                state = 'levelup'

            # Win / death checks
            if elapsed >= LEVEL_DURATION_SECONDS:
                state = 'win'
            if player.hp <= 0:
                state = 'dead'

        # ----- Drawing -----
        screen.fill((90, 160, 110))  # background base (grass)

        if state in ('playing', 'levelup', 'dead', 'win'):
            # recompute camera for safety outside playing loop too
            cam_x = clamp(player.x - SCREEN_W / 2, 0, WORLD_W - SCREEN_W)
            cam_y = clamp(player.y - SCREEN_H / 2, 0, WORLD_H - SCREEN_H)

            # draw ground (grid for reference)
            grid_color = (80, 130, 90)
            for gx in range(0, WORLD_W, 200):
                sx, _ = world_to_screen(gx, 0)
                pygame.draw.line(screen, grid_color, (sx, 0), (sx, SCREEN_H), 1)
            for gy in range(0, WORLD_H, 200):
                _, sy = world_to_screen(0, gy)
                pygame.draw.line(screen, grid_color, (0, sy), (SCREEN_W, sy), 1)

            # draw obstacles
            for o in obstacles:
                sx, sy = world_to_screen(o.rect.x, o.rect.y)
                # different visuals per kind
                if o.kind == 'tree':
                    pygame.draw.rect(screen, (40, 90, 30), (sx, sy, o.rect.w, o.rect.h))
                elif o.kind == 'rock':
                    pygame.draw.rect(screen, (110, 110, 110), (sx, sy, o.rect.w, o.rect.h))
                elif o.kind == 'house':
                    pygame.draw.rect(screen, (150, 100, 70), (sx, sy, o.rect.w, o.rect.h))
                elif o.kind == 'water':
                    pygame.draw.rect(screen, (30, 80, 140), (sx, sy, o.rect.w, o.rect.h))
                else:
                    pygame.draw.rect(screen, (210, 200, 80), (sx, sy, o.rect.w, o.rect.h))

            # draw lava pools under entities
            for lava in lava_pools:
                sx, sy = world_to_screen(lava.x, lava.y)
                alpha = int(160 * max(0.2, lava.duration / 6.0))
                surf = pygame.Surface((lava.radius * 2, lava.radius * 2), pygame.SRCALPHA)
                pygame.draw.circle(surf, (255, 120, 30, alpha), (lava.radius, lava.radius), int(lava.radius))
                screen.blit(surf, (sx - lava.radius, sy - lava.radius))

            # draw mobs
            for mob in mobs:
                sx, sy = world_to_screen(mob.x, mob.y)
                # health fraction
                maxhp = 22 + minute * 15
                frac = max(0.05, min(1.0, mob.hp / maxhp))
                color = (int(220 * frac + 30), int(80 * (1 - frac)), 70)
                pygame.draw.circle(screen, color, (int(sx), int(sy)), MOB_RADIUS)
                # simple HP bar
                bar_w = 28
                pygame.draw.rect(screen, (30, 30, 30), (sx - bar_w//2, sy - MOB_RADIUS - 10, bar_w, 6))
                pygame.draw.rect(screen, (180, 60, 60), (sx - bar_w//2, sy - MOB_RADIUS - 10, int(bar_w * frac), 6))

            # draw player (on top)
            px, py = world_to_screen(player.x, player.y)
            pygame.draw.circle(screen, (40, 110, 230), (int(px), int(py)), PLAYER_RADIUS)
            # draw player ring for attack range (faint)
            if player.attack_type == 'projectile':
                if player.attack_timer <= 0:
                    pygame.draw.circle(screen, (255, 255, 200), (int(px), int(py)), int(min(player.attack_range, 300)), 1)
            else:
                pygame.draw.circle(screen, (255, 255, 200), (int(px), int(py)), int(player.attack_range), 2)

            # draw projectiles
            for p in projectile_list:
                sx, sy = world_to_screen(p.x, p.y)
                col = (230, 140, 40) if p.owner == 'player' else (40, 40, 40)
                pygame.draw.circle(screen, col, (int(sx), int(sy)), 5)

            # HUD
            remaining = max(0, int(LEVEL_DURATION_SECONDS - elapsed))
            mins = remaining // 60
            secs = remaining % 60
            hud = font.render(f'Time {mins:02d}:{secs:02d}  HP {int(player.hp)}  Lv {player.level}  XP {player.xp}/{player.level*5}  Champ {CHAMPIONS[player.champion]["name"]}', True, (20, 20, 20))
            screen.blit(hud, (8, 8))

        # level up menu
        if state == 'levelup':
            overlay = pygame.Surface((SCREEN_W, SCREEN_H), pygame.SRCALPHA)
            overlay.fill((10, 10, 20, 200))
            screen.blit(overlay, (0, 0))
            title = big.render('Level Up! Choose a bonus', True, (255, 240, 180))
            screen.blit(title, (SCREEN_W // 2 - title.get_width() // 2, 80))
            opts = [
                f'1) + Damage ({int(8 + player.level*2)} dmg)',
                '2) + Speed (movement)',
                '3) + Max HP & heal',
            ]
            for i, t in enumerate(opts):
                txt = font.render(t, True, (230, 230, 230))
                screen.blit(txt, (SCREEN_W // 2 - txt.get_width() // 2, 180 + i * 36))
            hint = font.render('Press 1/2/3 to choose', True, (200, 200, 200))
            screen.blit(hint, (SCREEN_W // 2 - hint.get_width() // 2, 320))

        if state == 'win':
            overlay = pygame.Surface((SCREEN_W, SCREEN_H), pygame.SRCALPHA)
            overlay.fill((0, 0, 0, 160))
            screen.blit(overlay, (0, 0))
            text = big.render("You survived the level!", True, (255, 220, 120))
            screen.blit(text, (SCREEN_W // 2 - text.get_width() // 2, SCREEN_H // 2 - 20))

        if state == 'dead':
            overlay = pygame.Surface((SCREEN_W, SCREEN_H), pygame.SRCALPHA)
            overlay.fill((0, 0, 0, 200))
            screen.blit(overlay, (0, 0))
            text = big.render('You died — try again!', True, (255, 140, 140))
            screen.blit(text, (SCREEN_W // 2 - text.get_width() // 2, SCREEN_H // 2 - 20))

        pygame.display.flip()

    pygame.quit()
    sys.exit()

if __name__ == '__main__':
    main()
