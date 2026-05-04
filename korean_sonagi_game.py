from __future__ import annotations

import math
import os
import random
from dataclasses import dataclass, field
from pathlib import Path

import pygame

WIDTH = 960
HEIGHT = 720
FPS = 60
TOTAL_LEVELS = 10
WORDS_PER_LEVEL = 10
GAME_TITLE = "소나기"
ROOT = Path(__file__).resolve().parent

LEVEL_WORDS: list[list[str]] = [
    ["사과", "바람", "구름", "하늘", "물방울", "무지개", "소나기", "연필", "책상", "창문"],
    ["기차", "우산", "고양이", "강아지", "별빛", "달빛", "바다", "섬", "파도", "갈매기"],
    ["봄꽃", "여름", "가을", "겨울", "소나무", "산책", "다람쥐", "토끼", "참새", "나뭇잎"],
    ["아침", "점심", "저녁", "행복", "미소", "친구", "가족", "학교", "운동장", "강물"],
    ["한글", "타자", "연습", "속도", "정확", "도전", "성장", "빛나다", "반짝임", "환영"],
    ["파란색", "보라색", "초록색", "노란색", "오렌지", "분홍색", "빨간색", "검은색", "하얀색", "회색"],
    ["구름길", "우주", "은하", "행성", "별자리", "돛단배", "등대", "모래사장", "파도소리", "햇살"],
    ["기쁨", "용기", "희망", "평온", "열정", "감사", "배려", "성실", "집중", "반복"],
    ["달리기", "점프", "새싹", "꽃잎", "물결", "바람결", "햇볕", "비눗방울", "나비", "청명"],
    ["완주", "축하", "대성공", "최고", "왕관", "불꽃", "박수", "찬란", "빛내다", "소나기"]
]

FONT_CANDIDATES = [
    "/System/Library/Fonts/AppleGothic.ttf",
    "/System/Library/Fonts/Supplemental/AppleGothic.ttf",
    "/System/Library/Fonts/Supplemental/Apple SD Gothic Neo.ttc",
    "/System/Library/Fonts/Supplemental/Noto Sans CJK KR Regular.otf",
    "/Library/Fonts/AppleGothic.ttf",
    "/Library/Fonts/Apple SD Gothic Neo.ttf",
]

BG_COLOR = (18, 22, 34)
PANEL = (28, 36, 54)
TEXT = (240, 244, 255)
MUTED = (170, 180, 200)
ACCENT = (111, 227, 255)
WORD_COLOR = (255, 245, 190)
WORD_GLOW = (100, 160, 255)
GOOD = (110, 245, 170)
BAD = (255, 110, 110)
WARN = (255, 210, 100)


@dataclass
class FallingWord:
    word: str
    x: float
    y: float
    speed: float
    wobble_phase: float

    def update(self, dt: float) -> None:
        self.y += self.speed * dt
        self.x += math.sin(self.wobble_phase + self.y / 70.0) * 8.0 * dt


@dataclass
class CelebrationParticle:
    x: float
    y: float
    vx: float
    vy: float
    color: tuple[int, int, int]
    life: float
    radius: float

    def update(self, dt: float) -> None:
        self.vy += 320 * dt
        self.x += self.vx * dt
        self.y += self.vy * dt
        self.life -= dt


@dataclass
class GameState:
    screen: pygame.Surface
    clock: pygame.time.Clock
    font_large: pygame.font.Font
    font_mid: pygame.font.Font
    font_small: pygame.font.Font
    font_tiny: pygame.font.Font
    current_state: str = "start"
    level: int = 1
    score: int = 0
    input_text: str = ""
    target_word: str = ""
    words: list[FallingWord] = field(default_factory=list)
    used_words: set[str] = field(default_factory=set)
    level_hits: int = 0
    message: str = ""
    message_timer: float = 0.0
    shake_timer: float = 0.0
    celebration: list[CelebrationParticle] = field(default_factory=list)
    stars: list[tuple[float, float, float]] = field(default_factory=list)
    sound_ok: bool = False
    sfx_hit: pygame.mixer.Sound | None = None
    sfx_level: pygame.mixer.Sound | None = None
    sfx_win: pygame.mixer.Sound | None = None


def choose_font(size: int, bold: bool = False) -> pygame.font.Font:
    for path in FONT_CANDIDATES:
        if os.path.exists(path):
            try:
                return pygame.font.Font(path, size)
            except Exception:
                continue
    return pygame.font.SysFont(["Apple SD Gothic Neo", "AppleGothic", "Noto Sans CJK KR", "Malgun Gothic"], size, bold=bold)


def make_tone(frequency: float, duration: float, volume: float = 0.35, fade: float = 0.02) -> pygame.mixer.Sound:
    sample_rate = 44100
    n_samples = max(1, int(sample_rate * duration))
    pcm = bytearray()
    for i in range(n_samples):
        t = i / sample_rate
        envelope = 1.0
        if t < fade:
            envelope = t / fade
        elif duration - t < fade:
            envelope = max(0.0, (duration - t) / fade)
        wave_val = math.sin(2.0 * math.pi * frequency * t)
        sample = int(max(-1.0, min(1.0, wave_val)) * 32767 * volume * envelope)
        pcm += int(sample).to_bytes(2, byteorder="little", signed=True)
    return pygame.mixer.Sound(buffer=bytes(pcm))


def setup_audio() -> tuple[bool, pygame.mixer.Sound | None, pygame.mixer.Sound | None, pygame.mixer.Sound | None]:
    try:
        pygame.mixer.init(frequency=44100, size=-16, channels=1, buffer=512)
        return (
            True,
            make_tone(740, 0.09, 0.32),
            make_tone(520, 0.16, 0.32),
            make_tone(880, 0.6, 0.28),
        )
    except Exception:
        return False, None, None, None


def stars() -> list[tuple[float, float, float]]:
    rng = random.Random(7)
    return [(rng.uniform(0, WIDTH), rng.uniform(0, HEIGHT), rng.uniform(0.6, 1.8)) for _ in range(90)]


def reset_level(state: GameState) -> None:
    state.words.clear()
    state.used_words.clear()
    state.input_text = ""
    state.level_hits = 0
    state.message = f"{state.level}단계 시작!"
    state.message_timer = 1.4
    state.shake_timer = 0.0
    state.target_word = ""
    rng = random.Random(1000 + state.level)
    pool = LEVEL_WORDS[state.level - 1][:]
    rng.shuffle(pool)
    speed_base = 55 + (state.level - 1) * 28
    for i, word in enumerate(pool[:WORDS_PER_LEVEL]):
        x = 90 + (i % 5) * 170 + rng.uniform(-25, 25)
        y = rng.uniform(-520, -40) - i * 70
        speed = speed_base + rng.uniform(-12, 36)
        state.words.append(FallingWord(word, x, y, speed, rng.uniform(0, math.tau)))
    state.words.sort(key=lambda w: w.y)
    state.current_state = "playing"


def new_game(state: GameState) -> None:
    state.level = 1
    state.score = 0
    state.celebration.clear()
    reset_level(state)


def start_screen(state: GameState) -> None:
    state.current_state = "start"
    state.message = ""
    state.message_timer = 0.0


def next_level(state: GameState) -> None:
    if state.sfx_level:
        state.sfx_level.play()
    if state.level >= TOTAL_LEVELS:
        state.current_state = "victory"
        state.message = "최종 승리!"
        state.message_timer = 3.0
        spawn_celebration(state, 180)
        if state.sfx_win:
            state.sfx_win.play()
        return
    state.level += 1
    reset_level(state)


def spawn_celebration(state: GameState, count: int = 100) -> None:
    rng = random.Random()
    palette = [GOOD, ACCENT, WARN, (255, 140, 220), (255, 255, 255)]
    for _ in range(count):
        x = rng.uniform(80, WIDTH - 80)
        y = rng.uniform(60, HEIGHT * 0.6)
        angle = rng.uniform(0, math.tau)
        speed = rng.uniform(140, 460)
        state.celebration.append(
            CelebrationParticle(
                x=x,
                y=y,
                vx=math.cos(angle) * speed,
                vy=math.sin(angle) * speed - 180,
                color=rng.choice(palette),
                life=rng.uniform(1.4, 2.8),
                radius=rng.uniform(2.0, 5.0),
            )
        )


def render_text(surface: pygame.Surface, font: pygame.font.Font, text: str, color: tuple[int, int, int], x: float, y: float, center: bool = False) -> None:
    img = font.render(text, True, color)
    rect = img.get_rect()
    if center:
        rect.center = (x, y)
    else:
        rect.topleft = (x, y)
    surface.blit(img, rect)


def draw_word(surface: pygame.Surface, font: pygame.font.Font, word: FallingWord) -> None:
    shadow = font.render(word.word, True, WORD_GLOW)
    base = font.render(word.word, True, WORD_COLOR)
    rect = base.get_rect(center=(int(word.x), int(word.y)))
    surface.blit(shadow, shadow.get_rect(center=(rect.centerx + 2, rect.centery + 2)))
    surface.blit(base, rect)


def handle_typing(state: GameState) -> None:
    typed = state.input_text.strip()
    if not typed:
        return
    for word in list(state.words):
        if typed == word.word:
            state.words.remove(word)
            state.score += 100 + state.level * 20
            state.level_hits += 1
            state.input_text = ""
            state.target_word = ""
            state.message = f"맞췄다! {word.word}"
            state.message_timer = 0.8
            if state.sfx_hit:
                state.sfx_hit.play()
            if not state.words:
                next_level(state)
            return
    if state.target_word and not state.target_word.startswith(typed):
        state.message = "다시 입력해보세요"
        state.message_timer = 0.6


def update_game(state: GameState, dt: float) -> None:
    if state.message_timer > 0:
        state.message_timer -= dt
        if state.message_timer <= 0:
            state.message = ""
    if state.shake_timer > 0:
        state.shake_timer -= dt
    for word in state.words:
        word.update(dt)
        if word.y > HEIGHT - 70:
            state.current_state = "gameover"
            state.message = f"{word.word} 가 바닥에 닿았습니다"
            state.message_timer = 0.0
            state.shake_timer = 0.0
            return
    if state.current_state == "victory":
        spawn_celebration(state, 3)
    for particle in list(state.celebration):
        particle.update(dt)
        if particle.life <= 0:
            state.celebration.remove(particle)

    if state.words:
        state.target_word = min(state.words, key=lambda w: w.y).word


def draw_background(surface: pygame.Surface, state: GameState, time_acc: float) -> None:
    surface.fill(BG_COLOR)
    for i, (x, y, speed) in enumerate(state.stars):
        yy = (y + time_acc * speed * 18) % HEIGHT
        color = (70 + (i % 3) * 30, 90 + (i % 5) * 25, 120 + (i % 7) * 16)
        pygame.draw.circle(surface, color, (int(x), int(yy)), 1)
    for i in range(18):
        px = int((time_acc * 80 + i * 120) % (WIDTH + 120) - 60)
        pygame.draw.circle(surface, (35, 50, 70), (px, 70 + (i % 4) * 18), 3)


def draw_panel(surface: pygame.Surface) -> pygame.Rect:
    panel = pygame.Rect(24, HEIGHT - 144, WIDTH - 48, 120)
    pygame.draw.rect(surface, PANEL, panel, border_radius=20)
    pygame.draw.rect(surface, (76, 92, 120), panel, width=2, border_radius=20)
    return panel


def draw_input_box(surface: pygame.Surface, state: GameState, panel: pygame.Rect) -> None:
    box = pygame.Rect(panel.left + 24, panel.top + 50, panel.width - 48, 48)
    pygame.draw.rect(surface, (18, 24, 40), box, border_radius=14)
    pygame.draw.rect(surface, ACCENT, box, width=2, border_radius=14)
    render_text(surface, state.font_mid, state.input_text or "여기에 한글을 입력하세요", MUTED if not state.input_text else TEXT, box.left + 16, box.top + 10)
    caret_x = box.left + 16 + state.font_mid.size(state.input_text)[0] + 4
    if int(pygame.time.get_ticks() / 450) % 2 == 0:
        pygame.draw.line(surface, TEXT, (caret_x, box.top + 10), (caret_x, box.bottom - 10), 2)


def draw_game(state: GameState, time_acc: float) -> None:
    surface = state.screen
    draw_background(surface, state, time_acc)
    if state.shake_timer > 0:
        offset = random.randint(-4, 4)
    else:
        offset = 0
    level_text = f"레벨 {state.level}/{TOTAL_LEVELS}"
    render_text(surface, state.font_large, GAME_TITLE, TEXT, 32 + offset, 18)
    render_text(surface, state.font_mid, level_text, ACCENT, WIDTH - 210 + offset, 26)
    render_text(surface, state.font_mid, f"점수 {state.score}", GOOD, WIDTH - 210 + offset, 60)
    render_text(surface, state.font_small, f"남은 단어 {len(state.words)} / {WORDS_PER_LEVEL}", MUTED, WIDTH - 210 + offset, 92)

    if state.current_state in {"start", "gameover"}:
        overlay = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        overlay.fill((8, 12, 24, 160))
        surface.blit(overlay, (0, 0))

    if state.current_state == "start":
        render_text(surface, state.font_large, "소나기", TEXT, WIDTH // 2, 170, center=True)
        render_text(surface, state.font_mid, "한글 단어를 타이핑해서 비를 멈추세요", TEXT, WIDTH // 2, 230, center=True)
        render_text(surface, state.font_small, "Enter 또는 Space로 시작", ACCENT, WIDTH // 2, 290, center=True)
        for idx, line in enumerate([
            "• 총 10레벨, 각 레벨마다 10개의 단어",
            "• 단어를 정확히 입력하면 사라집니다",
            "• 바닥에 닿으면 게임 오버",
        ]):
            render_text(surface, state.font_small, line, MUTED, WIDTH // 2, 355 + idx * 34, center=True)
    elif state.current_state == "gameover":
        render_text(surface, state.font_large, "게임 오버", BAD, WIDTH // 2, 200, center=True)
        render_text(surface, state.font_mid, state.message, TEXT, WIDTH // 2, 260, center=True)
        render_text(surface, state.font_mid, "R 키로 다시 시작", ACCENT, WIDTH // 2, 320, center=True)
    elif state.current_state == "victory":
        render_text(surface, state.font_large, "축하합니다!", GOOD, WIDTH // 2, 150, center=True)
        render_text(surface, state.font_mid, "모든 소나기를 이겨냈습니다", TEXT, WIDTH // 2, 212, center=True)
        render_text(surface, state.font_mid, f"최종 점수 {state.score}", WARN, WIDTH // 2, 268, center=True)
        render_text(surface, state.font_small, "R 키로 다시 시작", ACCENT, WIDTH // 2, 320, center=True)

    panel = draw_panel(surface)
    draw_input_box(surface, state, panel)
    render_text(surface, state.font_small, f"현재 입력: {state.input_text}", MUTED, panel.left + 24, panel.top + 14)
    if state.message:
        render_text(surface, state.font_small, state.message, WARN if state.current_state == "playing" else TEXT, panel.right - 28, panel.top + 14, center=False)

    for word in state.words:
        draw_word(surface, state.font_mid, word)

    for particle in state.celebration:
        alpha = max(0, min(255, int(255 * (particle.life / 2.8))))
        color = (*particle.color[:3], alpha)
        dot = pygame.Surface((12, 12), pygame.SRCALPHA)
        pygame.draw.circle(dot, color, (6, 6), int(particle.radius))
        surface.blit(dot, (particle.x, particle.y))


def save_optional_launcher_note() -> None:
    pass


def main() -> int:
    pygame.init()
    pygame.display.set_caption(GAME_TITLE)
    screen = pygame.display.set_mode((WIDTH, HEIGHT))
    clock = pygame.time.Clock()
    font_large = choose_font(56, True)
    font_mid = choose_font(30)
    font_small = choose_font(22)
    font_tiny = choose_font(16)
    sound_ok, sfx_hit, sfx_level, sfx_win = setup_audio()
    state = GameState(
        screen=screen,
        clock=clock,
        font_large=font_large,
        font_mid=font_mid,
        font_small=font_small,
        font_tiny=font_tiny,
        sound_ok=sound_ok,
        sfx_hit=sfx_hit,
        sfx_level=sfx_level,
        sfx_win=sfx_win,
        stars=stars(),
    )
    start_screen(state)
    pygame.key.start_text_input()
    pygame.key.set_text_input_rect(pygame.Rect(80, HEIGHT - 90, WIDTH - 160, 48))
    time_acc = 0.0
    running = True
    while running:
        dt = state.clock.tick(FPS) / 1000.0
        time_acc += dt
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN:
                if event.key in (pygame.K_ESCAPE, pygame.K_q):
                    running = False
                elif event.key == pygame.K_BACKSPACE:
                    state.input_text = state.input_text[:-1]
                elif event.key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE):
                    if state.current_state == "start":
                        new_game(state)
                    elif state.current_state in {"gameover", "victory"}:
                        new_game(state)
                    else:
                        handle_typing(state)
            elif event.type == pygame.TEXTINPUT:
                if state.current_state == "playing":
                    state.input_text += event.text
                    handle_typing(state)
            elif event.type == pygame.TEXTEDITING:
                pass
            elif event.type == pygame.MOUSEBUTTONDOWN and state.current_state == "start":
                new_game(state)

        if state.current_state == "playing":
            update_game(state, dt)
            if state.input_text and state.words:
                state.target_word = min(state.words, key=lambda w: len(w.word)).word

        if state.current_state == "victory":
            update_game(state, dt)

        draw_game(state, time_acc)
        if state.sound_ok:
            render_text(state.screen, state.font_tiny, "사운드 활성화", GOOD, WIDTH - 128, HEIGHT - 26)
        else:
            render_text(state.screen, state.font_tiny, "사운드 없음", MUTED, WIDTH - 108, HEIGHT - 26)
        pygame.display.flip()
    pygame.quit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
