#!/usr/bin/env python3
import random
import tkinter as tk
from tkinter import font

WIDTH = 900
HEIGHT = 650
TOP_MARGIN = 70
BOTTOM_LINE = HEIGHT - 75
TICK_MS = 25
MAX_STAGE = 10
WORDS_PER_STAGE = 10

WORDS = [
    "가방", "나무", "하늘", "바다", "사과", "고양이", "강아지", "학교", "친구", "사랑",
    "구름", "노래", "마음", "바람", "꽃잎", "달빛", "햇살", "별빛", "겨울", "여름",
    "봄날", "가을", "연필", "책상", "의자", "창문", "기차", "버스", "도로", "시장",
    "우산", "소풍", "그림", "편지", "전화", "약속", "희망", "기쁨", "웃음", "눈물",
    "산책", "운동", "음악", "영화", "요리", "김치", "라면", "바나나", "포도", "딸기",
    "호수", "강물", "숲길", "언덕", "마을", "도시", "공원", "놀이터", "비행기", "자전거",
    "컴퓨터", "키보드", "마우스", "화면", "시간", "시계", "오늘", "내일", "어제", "추억",
    "용기", "성공", "도전", "행복", "평화", "건강", "가족", "선물", "축제", "여행",
    "소나기", "무지개", "번개", "천둥", "파도", "모래", "조개", "등대", "항구", "섬마을",
    "한글", "타자", "속도", "정확", "집중", "승리", "완주", "단계", "폭죽", "축하",
    "은하수", "수박", "복숭아", "감나무", "참새", "토끼", "다람쥐", "호랑이", "곰돌이", "여우",
    "청소", "빨래", "설거지", "냉장고", "부엌", "거실", "침대", "이불", "베개", "커튼",
    "도서관", "박물관", "미술관", "운동장", "교실", "선생님", "학생", "문제", "정답", "연습",
]


class FallingWord:
    def __init__(self, canvas, text, x, y, speed, word_font):
        self.canvas = canvas
        self.text = text
        self.speed = speed
        self.item = canvas.create_text(x, y, text=text, fill="#17324d", font=word_font, anchor="n")
        self.bbox = canvas.bbox(self.item)

    def move(self):
        self.canvas.move(self.item, 0, self.speed)
        self.bbox = self.canvas.bbox(self.item)

    def bottom(self):
        return self.bbox[3] if self.bbox else 0

    def overlaps(self, other_bbox, padding=16):
        if not self.bbox or not other_bbox:
            return False
        ax1, ay1, ax2, ay2 = self.bbox
        bx1, by1, bx2, by2 = other_bbox
        return ax1 - padding < bx2 and ax2 + padding > bx1 and ay1 - padding < by2 and ay2 + padding > by1


class TypeGame:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("한글 소나기 타자 게임")
        self.root.resizable(False, False)

        self.title_font = font.Font(family="AppleGothic", size=24, weight="bold")
        self.ui_font = font.Font(family="AppleGothic", size=16)
        self.word_font = font.Font(family="AppleGothic", size=22, weight="bold")
        self.big_font = font.Font(family="AppleGothic", size=36, weight="bold")

        self.canvas = tk.Canvas(self.root, width=WIDTH, height=HEIGHT, bg="#eaf7ff", highlightthickness=0)
        self.canvas.pack()

        self.input_var = tk.StringVar()
        self.entry = tk.Entry(self.root, textvariable=self.input_var, font=self.ui_font, justify="center")
        self.entry.place(x=WIDTH // 2 - 170, y=HEIGHT - 52, width=340, height=36)
        self.bind_return(self.check_input)
        self.entry.bind("<KeyRelease>", self.handle_key_release)

        self.stage = 1
        self.score = 0
        self.cleared = 0
        self.missed = 0
        self.words = []
        self.spawned = 0
        self.running = False
        self.after_id = None

        self.draw_static()
        self.show_start()
        self.root.mainloop()

    def draw_static(self):
        self.canvas.delete("static")
        self.canvas.create_rectangle(0, 0, WIDTH, TOP_MARGIN, fill="#bde8ff", outline="", tags="static")
        self.canvas.create_line(0, BOTTOM_LINE, WIDTH, BOTTOM_LINE, fill="#ff7676", width=3, tags="static")
        self.canvas.create_text(WIDTH // 2, 31, text="한글 소나기 타자 게임", fill="#0b4f7a", font=self.title_font, tags="static")
        self.status_item = self.canvas.create_text(18, 56, text="", anchor="w", fill="#16425b", font=self.ui_font, tags="static")
        self.help_item = self.canvas.create_text(WIDTH - 18, 56, text="단어를 입력하면 터집니다", anchor="e", fill="#16425b", font=self.ui_font, tags="static")

    def bind_return(self, callback):
        self.entry.bind("<Return>", lambda event: (event, callback())[1])

    def handle_key_release(self, event):
        event.keysym
        self.check_input()

    def show_start(self):
        self.canvas.delete("message")
        self.canvas.create_text(WIDTH // 2, HEIGHT // 2 - 60, text="시작하려면 Enter", fill="#0b4f7a", font=self.big_font, tags="message")
        self.canvas.create_text(WIDTH // 2, HEIGHT // 2, text="1단계부터 10단계까지 한글 단어를 모두 맞혀보세요", fill="#31546b", font=self.ui_font, tags="message")
        self.entry.focus_set()
        self.bind_return(self.start_from_enter)
        self.update_status()

    def start_from_enter(self):
        self.bind_return(self.check_input)
        self.start_stage()

    def start_stage(self):
        self.canvas.delete("message")
        self.clear_words()
        self.input_var.set("")
        self.cleared = 0
        self.missed = 0
        self.spawned = 0
        self.running = True
        self.update_status()
        self.spawn_word()
        self.game_loop()

    def clear_words(self):
        for word in self.words:
            self.canvas.delete(word.item)
        self.words = []

    def stage_target(self):
        return WORDS_PER_STAGE + self.stage - 1

    def stage_speed(self):
        return 1.3 + self.stage * 0.35

    def spawn_delay(self):
        return max(300, 1150 - self.stage * 75)

    def spawn_word(self):
        if not self.running or self.spawned >= self.stage_target():
            return

        text = random.choice(WORDS)
        x = self.find_free_x(text)
        word = FallingWord(self.canvas, text, x, TOP_MARGIN + 8, self.stage_speed(), self.word_font)
        self.words.append(word)
        self.spawned += 1
        self.update_status()
        self.root.after(self.spawn_delay(), self.spawn_word)

    def find_free_x(self, text):
        width = self.word_font.measure(text) + 28
        min_x = max(width // 2, 35)
        max_x = WIDTH - min_x
        for _ in range(80):
            x = random.randint(min_x, max_x)
            temp = (x - width // 2, TOP_MARGIN, x + width // 2, TOP_MARGIN + 42)
            if all(not word.overlaps(temp, padding=24) for word in self.words):
                return x
        lanes = list(range(min_x, max_x + 1, max(width, 70)))
        random.shuffle(lanes)
        for x in lanes:
            temp = (x - width // 2, TOP_MARGIN, x + width // 2, TOP_MARGIN + 42)
            if all(not word.overlaps(temp, padding=12) for word in self.words):
                return x
        return random.randint(min_x, max_x)

    def game_loop(self):
        if not self.running:
            return

        missed_now = []
        for word in list(self.words):
            word.move()
            if word.bottom() >= BOTTOM_LINE:
                missed_now.append(word)

        for word in missed_now:
            self.remove_word(word)
            self.missed += 1

        self.update_status()
        self.check_stage_end()
        if self.running:
            self.after_id = self.root.after(TICK_MS, self.game_loop)

    def check_input(self):
        if not self.running:
            return
        typed = self.input_var.get().strip()
        if not typed:
            return

        for word in list(self.words):
            if word.text == typed:
                self.burst(word)
                self.remove_word(word)
                self.input_var.set("")
                self.cleared += 1
                self.score += 10 * self.stage
                self.update_status()
                self.check_stage_end()
                return

    def burst(self, word):
        bbox = self.canvas.bbox(word.item)
        if not bbox:
            return
        x = (bbox[0] + bbox[2]) // 2
        y = (bbox[1] + bbox[3]) // 2
        colors = ["#ff4d6d", "#ffd166", "#06d6a0", "#4cc9f0", "#f72585"]
        for i in range(10):
            dx = random.randint(-35, 35)
            dy = random.randint(-25, 25)
            piece = self.canvas.create_oval(x + dx, y + dy, x + dx + 8, y + dy + 8, fill=random.choice(colors), outline="")
            self.root.after(220 + i * 12, lambda item=piece: self.canvas.delete(item))

    def remove_word(self, word):
        if word in self.words:
            self.words.remove(word)
        self.canvas.delete(word.item)

    def check_stage_end(self):
        if self.spawned < self.stage_target() or self.words:
            return
        self.running = False
        if self.stage >= MAX_STAGE:
            self.show_victory()
        else:
            self.show_stage_clear()

    def show_stage_clear(self):
        self.canvas.delete("message")
        self.canvas.create_text(WIDTH // 2, HEIGHT // 2 - 45, text=f"{self.stage}단계 완료!", fill="#0b8f4d", font=self.big_font, tags="message")
        self.canvas.create_text(WIDTH // 2, HEIGHT // 2 + 15, text="Enter를 누르면 다음 단계로 갑니다", fill="#31546b", font=self.ui_font, tags="message")
        self.stage += 1
        self.bind_return(self.next_stage_from_enter)

    def next_stage_from_enter(self):
        self.bind_return(self.check_input)
        self.start_stage()

    def show_victory(self):
        self.canvas.delete("message")
        self.clear_words()
        self.canvas.create_text(WIDTH // 2, HEIGHT // 2 - 80, text="축하합니다!", fill="#e63946", font=self.big_font, tags="message")
        self.canvas.create_text(WIDTH // 2, HEIGHT // 2 - 20, text="10단계를 모두 깼습니다", fill="#0b4f7a", font=self.title_font, tags="message")
        self.canvas.create_text(WIDTH // 2, HEIGHT // 2 + 35, text=f"최종 점수: {self.score}점", fill="#31546b", font=self.ui_font, tags="message")
        self.canvas.create_text(WIDTH // 2, HEIGHT // 2 + 85, text="다시 하려면 Enter", fill="#31546b", font=self.ui_font, tags="message")
        self.fireworks()
        self.bind_return(self.restart_from_enter)

    def fireworks(self):
        colors = ["#ff006e", "#fb5607", "#ffbe0b", "#8338ec", "#3a86ff", "#06d6a0"]
        for _ in range(70):
            x = random.randint(80, WIDTH - 80)
            y = random.randint(110, HEIGHT - 150)
            size = random.randint(5, 12)
            item = self.canvas.create_oval(x, y, x + size, y + size, fill=random.choice(colors), outline="", tags="message")
            self.root.after(random.randint(900, 1800), lambda item=item: self.canvas.delete(item))

    def restart_from_enter(self):
        self.stage = 1
        self.score = 0
        self.bind_return(self.check_input)
        self.start_stage()

    def update_status(self):
        target = self.stage_target()
        self.canvas.itemconfigure(
            self.status_item,
            text=f"단계 {self.stage}/{MAX_STAGE}   맞힘 {self.cleared}/{target}   놓침 {self.missed}   점수 {self.score}",
        )


if __name__ == "__main__":
    TypeGame()
