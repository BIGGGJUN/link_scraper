import csv
import queue
import re
import threading
import tkinter as tk
import webbrowser
from tkinter import ttk, filedialog, messagebox
from tkinter.scrolledtext import ScrolledText
from urllib.parse import urlparse

import requests


class LinkCheckerApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("링크 문자열 검사기")
        self.root.geometry("1180x760")

        self.stop_requested = False
        self.worker_thread = None
        self.result_rows = []
        self.ui_queue = queue.Queue()

        self._build_ui()
        self._poll_ui_queue()

    def _build_ui(self):
        top_frame = ttk.Frame(self.root, padding=10)
        top_frame.pack(fill="x")

        file_frame = ttk.LabelFrame(top_frame, text="링크 파일", padding=10)
        file_frame.pack(fill="x", pady=(0, 10))

        self.file_var = tk.StringVar()

        ttk.Entry(file_frame, textvariable=self.file_var).pack(side="left", fill="x", expand=True, padx=(0, 8))
        ttk.Button(file_frame, text="파일 선택", command=self.select_file).pack(side="left", padx=(0, 8))
        ttk.Button(file_frame, text="링크 미리보기", command=self.preview_links).pack(side="left")

        options_frame = ttk.Frame(top_frame)
        options_frame.pack(fill="x", pady=(0, 10))

        left_frame = ttk.LabelFrame(options_frame, text="목표 문자열", padding=10)
        left_frame.pack(side="left", fill="both", expand=True, padx=(0, 5))

        self.targets_text = ScrolledText(left_frame, height=8)
        self.targets_text.pack(fill="both", expand=True)
        self.targets_text.insert("1.0", "예시 문자열 1\n예시 문자열 2\n")

        right_frame = ttk.LabelFrame(options_frame, text="검사 옵션", padding=10)
        right_frame.pack(side="left", fill="y", padx=(5, 0))

        self.timeout_var = tk.StringVar(value="10")
        self.user_agent_var = tk.StringVar(
            value="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
        )
        self.ignore_case_var = tk.BooleanVar(value=True)
        self.follow_redirects_var = tk.BooleanVar(value=True)
        self.verify_ssl_var = tk.BooleanVar(value=True)
        self.strip_comments_var = tk.BooleanVar(value=False)

        row = 0
        ttk.Label(right_frame, text="타임아웃(초)").grid(row=row, column=0, sticky="w")
        ttk.Entry(right_frame, textvariable=self.timeout_var, width=12).grid(row=row, column=1, sticky="w", padx=(8, 0))
        row += 1

        ttk.Label(right_frame, text="User-Agent").grid(row=row, column=0, sticky="nw", pady=(8, 0))
        ttk.Entry(right_frame, textvariable=self.user_agent_var, width=50).grid(
            row=row, column=1, sticky="w", padx=(8, 0), pady=(8, 0)
        )
        row += 1

        ttk.Checkbutton(right_frame, text="대소문자 무시", variable=self.ignore_case_var).grid(
            row=row, column=0, columnspan=2, sticky="w", pady=(8, 0)
        )
        row += 1
        ttk.Checkbutton(right_frame, text="리다이렉트 허용", variable=self.follow_redirects_var).grid(
            row=row, column=0, columnspan=2, sticky="w"
        )
        row += 1
        ttk.Checkbutton(right_frame, text="SSL 인증서 검증", variable=self.verify_ssl_var).grid(
            row=row, column=0, columnspan=2, sticky="w"
        )
        row += 1
        ttk.Checkbutton(right_frame, text="HTML 주석 제거 후 검사", variable=self.strip_comments_var).grid(
            row=row, column=0, columnspan=2, sticky="w"
        )

        action_frame = ttk.Frame(top_frame)
        action_frame.pack(fill="x", pady=(0, 10))

        self.start_button = ttk.Button(action_frame, text="검사 시작", command=self.start_check)
        self.start_button.pack(side="left", padx=(0, 8))

        self.stop_button = ttk.Button(action_frame, text="중지", command=self.stop_check, state="disabled")
        self.stop_button.pack(side="left", padx=(0, 8))

        ttk.Button(action_frame, text="결과 CSV 저장", command=self.save_csv).pack(side="left", padx=(0, 8))
        ttk.Button(action_frame, text="결과 지우기", command=self.clear_results).pack(side="left")

        progress_frame = ttk.Frame(top_frame)
        progress_frame.pack(fill="x", pady=(0, 10))

        self.progress_var = tk.StringVar(value="대기 중")
        ttk.Label(progress_frame, textvariable=self.progress_var).pack(side="left")

        self.progressbar = ttk.Progressbar(progress_frame, mode="determinate")
        self.progressbar.pack(side="left", fill="x", expand=True, padx=(12, 0))

        result_frame = ttk.LabelFrame(self.root, text="검사 결과", padding=10)
        result_frame.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        columns = ("url", "status", "http_code", "found_count", "found_targets", "missing_targets", "final_url", "error")
        self.tree = ttk.Treeview(result_frame, columns=columns, show="headings", height=18)

        headings = {
            "url": "원본 링크",
            "status": "상태",
            "http_code": "HTTP",
            "found_count": "발견 수",
            "found_targets": "발견된 문자열",
            "missing_targets": "미발견 문자열",
            "final_url": "최종 URL",
            "error": "오류",
        }

        widths = {
            "url": 220,
            "status": 90,
            "http_code": 70,
            "found_count": 70,
            "found_targets": 220,
            "missing_targets": 220,
            "final_url": 220,
            "error": 220,
        }

        for col in columns:
            self.tree.heading(col, text=headings[col])
            self.tree.column(col, width=widths[col], anchor="w")

        self.tree.bind("<Double-1>", self.open_selected_link)
        self.tree.bind("<Motion>", self.on_tree_motion)

        tree_scroll_y = ttk.Scrollbar(result_frame, orient="vertical", command=self.tree.yview)
        tree_scroll_x = ttk.Scrollbar(result_frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=tree_scroll_y.set, xscrollcommand=tree_scroll_x.set)

        self.tree.grid(row=0, column=0, sticky="nsew")
        tree_scroll_y.grid(row=0, column=1, sticky="ns")
        tree_scroll_x.grid(row=1, column=0, sticky="ew")

        result_frame.rowconfigure(0, weight=1)
        result_frame.columnconfigure(0, weight=1)

        log_frame = ttk.LabelFrame(self.root, text="로그", padding=10)
        log_frame.pack(fill="both", expand=False, padx=10, pady=(0, 10))

        self.log_text = ScrolledText(log_frame, height=8)
        self.log_text.pack(fill="both", expand=True)

    def log(self, message: str):
        self.log_text.insert("end", message + "\n")
        self.log_text.see("end")

    def select_file(self):
        path = filedialog.askopenfilename(
            title="링크 목록 텍스트 파일 선택",
            filetypes=[("Text Files", "*.txt"), ("All Files", "*.*")]
        )
        if path:
            self.file_var.set(path)

    def preview_links(self):
        path = self.file_var.get().strip()
        if not path:
            messagebox.showwarning("안내", "먼저 텍스트 파일을 선택하세요.")
            return

        try:
            links = self.load_links(path)
        except Exception as e:
            messagebox.showerror("오류", f"파일을 읽는 중 오류가 발생했습니다.\n{e}")
            return

        preview = "\n".join(links[:30])
        if len(links) > 30:
            preview += f"\n... 외 {len(links) - 30}개"

        messagebox.showinfo("링크 미리보기", f"총 {len(links)}개 링크\n\n{preview if preview else '(없음)'}")

    def load_links(self, path: str):
        with open(path, "r", encoding="utf-8-sig") as f:
            raw_lines = f.readlines()

        links = []
        seen = set()

        for line in raw_lines:
            line = line.strip()
            if not line:
                continue

            matches = re.findall(r"https?://[^\s<>\"]+|www\.[^\s<>\"]+", line)
            if matches:
                for m in matches:
                    url = m.strip()
                    if url.startswith("www."):
                        url = "http://" + url
                    if url not in seen:
                        seen.add(url)
                        links.append(url)
            else:
                maybe_url = line
                if maybe_url.startswith("www."):
                    maybe_url = "http://" + maybe_url
                if self.is_probably_url(maybe_url) and maybe_url not in seen:
                    seen.add(maybe_url)
                    links.append(maybe_url)

        return links

    @staticmethod
    def is_probably_url(value: str) -> bool:
        parsed = urlparse(value)
        return bool(parsed.scheme and parsed.netloc)

    def get_targets(self):
        lines = self.targets_text.get("1.0", "end").splitlines()
        targets = []
        seen = set()

        for line in lines:
            text = line.strip()
            if text and text not in seen:
                seen.add(text)
                targets.append(text)

        return targets

    def start_check(self):
        if self.worker_thread and self.worker_thread.is_alive():
            messagebox.showinfo("안내", "이미 검사 중입니다.")
            return

        path = self.file_var.get().strip()
        if not path:
            messagebox.showwarning("안내", "링크 파일을 선택하세요.")
            return

        try:
            timeout = float(self.timeout_var.get().strip())
            if timeout <= 0:
                raise ValueError
        except ValueError:
            messagebox.showwarning("안내", "타임아웃은 0보다 큰 숫자여야 합니다.")
            return

        targets = self.get_targets()
        if not targets:
            messagebox.showwarning("안내", "목표 문자열을 1개 이상 입력하세요.")
            return

        try:
            links = self.load_links(path)
        except Exception as e:
            messagebox.showerror("오류", f"링크 파일을 읽을 수 없습니다.\n{e}")
            return

        if not links:
            messagebox.showwarning("안내", "유효한 링크를 찾지 못했습니다.")
            return

        self.stop_requested = False
        self.result_rows.clear()
        self.tree.delete(*self.tree.get_children())

        self.start_button.config(state="disabled")
        self.stop_button.config(state="normal")
        self.progressbar["maximum"] = len(links)
        self.progressbar["value"] = 0
        self.progress_var.set(f"검사 시작: 0 / {len(links)}")

        options = {
            "timeout": timeout,
            "user_agent": self.user_agent_var.get().strip(),
            "ignore_case": self.ignore_case_var.get(),
            "follow_redirects": self.follow_redirects_var.get(),
            "verify_ssl": self.verify_ssl_var.get(),
            "strip_comments": self.strip_comments_var.get(),
        }

        self.worker_thread = threading.Thread(
            target=self.worker_run,
            args=(links, targets, options),
            daemon=True
        )
        self.worker_thread.start()

    def stop_check(self):
        self.stop_requested = True
        self.log("중지 요청됨")

    def worker_run(self, links, targets, options):
        session = requests.Session()
        session.headers.update({"User-Agent": options["user_agent"] or "Mozilla/5.0"})

        total = len(links)

        for idx, url in enumerate(links, start=1):
            if self.stop_requested:
                self.ui_queue.put(("log", "사용자 요청으로 검사 중단"))
                break

            self.ui_queue.put(("progress", idx - 1, total, f"검사 중: {idx - 1} / {total} | 현재 링크 준비: {url}"))
            result = self.check_url(session, url, targets, options)
            self.result_rows.append(result)
            self.ui_queue.put(("result", result))
            self.ui_queue.put(("progress", idx, total, f"검사 중: {idx} / {total} | 현재 링크 완료: {url}"))

        self.ui_queue.put(("done", None))

    def check_url(self, session, url, targets, options):
        result = {
            "url": url,
            "status": "실패",
            "http_code": "",
            "found_count": 0,
            "found_targets": [],
            "missing_targets": [],
            "final_url": "",
            "error": "",
        }

        try:
            resp = session.get(
                url,
                timeout=options["timeout"],
                allow_redirects=options["follow_redirects"],
                verify=options["verify_ssl"],
            )

            result["http_code"] = resp.status_code
            result["final_url"] = resp.url

            try:
                text = resp.text
            except Exception:
                text = resp.content.decode(resp.encoding or "utf-8", errors="ignore")

            if options["strip_comments"]:
                text = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)

            found, missing = self.find_targets(text, targets, options["ignore_case"])
            result["found_targets"] = found
            result["missing_targets"] = missing
            result["found_count"] = len(found)
            result["status"] = "성공" if resp.ok else "HTTP오류"

        except requests.exceptions.RequestException as e:
            result["error"] = str(e)
            result["status"] = "접속오류"
        except Exception as e:
            result["error"] = str(e)
            result["status"] = "예외"

        return result

    @staticmethod
    def find_targets(text: str, targets, ignore_case: bool):
        found = []
        missing = []

        source = text.lower() if ignore_case else text

        for target in targets:
            needle = target.lower() if ignore_case else target
            if needle in source:
                found.append(target)
            else:
                missing.append(target)

        return found, missing

    def add_result_to_tree(self, result):
        self.tree.insert(
            "",
            "end",
            values=(
                result["url"],
                result["status"],
                result["http_code"],
                result["found_count"],
                ", ".join(result["found_targets"]),
                ", ".join(result["missing_targets"]),
                result["final_url"],
                result["error"],
            )
        )

    def open_selected_link(self, event=None):
        item_id = self.tree.identify_row(event.y) if event else None

        if not item_id:
            selected = self.tree.selection()
            if not selected:
                return
            item_id = selected[0]

        values = self.tree.item(item_id, "values")
        if not values:
            return

        original_url = values[0].strip() if len(values) > 0 else ""
        final_url = values[6].strip() if len(values) > 6 else ""

        target_url = final_url or original_url
        if not target_url:
            messagebox.showwarning("안내", "열 수 있는 링크가 없습니다.")
            return

        if not target_url.startswith(("http://", "https://")):
            target_url = "http://" + target_url

        try:
            webbrowser.open(target_url)
            self.log(f"브라우저로 열기: {target_url}")
        except Exception as e:
            messagebox.showerror("오류", f"브라우저로 링크를 열지 못했습니다.\n{e}")

    def on_tree_motion(self, event):
        row_id = self.tree.identify_row(event.y)
        if row_id:
            self.tree.config(cursor="hand2")
        else:
            self.tree.config(cursor="")

    def save_csv(self):
        if not self.result_rows:
            messagebox.showinfo("안내", "저장할 결과가 없습니다.")
            return

        path = filedialog.asksaveasfilename(
            title="결과 CSV 저장",
            defaultextension=".csv",
            filetypes=[("CSV Files", "*.csv")]
        )
        if not path:
            return

        try:
            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f)
                writer.writerow([
                    "원본 링크",
                    "상태",
                    "HTTP 코드",
                    "발견 수",
                    "발견된 문자열",
                    "미발견 문자열",
                    "최종 URL",
                    "오류",
                ])
                for row in self.result_rows:
                    writer.writerow([
                        row["url"],
                        row["status"],
                        row["http_code"],
                        row["found_count"],
                        " | ".join(row["found_targets"]),
                        " | ".join(row["missing_targets"]),
                        row["final_url"],
                        row["error"],
                    ])
            messagebox.showinfo("완료", "CSV 저장이 완료되었습니다.")
        except Exception as e:
            messagebox.showerror("오류", f"CSV 저장 실패\n{e}")

    def clear_results(self):
        self.result_rows.clear()
        self.tree.delete(*self.tree.get_children())
        self.progressbar["value"] = 0
        self.progress_var.set("대기 중")
        self.log("결과 초기화 완료")

    def _poll_ui_queue(self):
        try:
            while True:
                item = self.ui_queue.get_nowait()
                kind = item[0]

                if kind == "log":
                    self.log(item[1])

                elif kind == "progress":
                    value, total, message = item[1], item[2], item[3]
                    self.progressbar["maximum"] = total
                    self.progressbar["value"] = value
                    self.progress_var.set(message)

                elif kind == "result":
                    result = item[1]
                    self.add_result_to_tree(result)
                    self.log(
                        f"[{result['status']}] {result['url']} | "
                        f"HTTP={result['http_code']} | "
                        f"발견={len(result['found_targets'])}개"
                    )

                elif kind == "done":
                    self.start_button.config(state="normal")
                    self.stop_button.config(state="disabled")
                    finished = len(self.result_rows)
                    self.progress_var.set(f"완료: {finished}개 처리")
                    self.log("검사 종료")

        except queue.Empty:
            pass

        self.root.after(100, self._poll_ui_queue)


def main():
    root = tk.Tk()
    try:
        style = ttk.Style()
        if "vista" in style.theme_names():
            style.theme_use("vista")
    except Exception:
        pass

    LinkCheckerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()