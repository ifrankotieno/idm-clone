import customtkinter as ctk


class VideoPicker(ctk.CTkToplevel):
    def __init__(self, parent, title, choices, complete):
        super().__init__(parent)
        self.title("Choose video format")
        self.geometry("500x400")
        self.resizable(False, False)
        self.transient(parent)
        self.choices = choices
        self.complete = complete
        self.finished = False
        display_title = title if len(title) <= 150 else title[:147] + "..."
        ctk.CTkLabel(self, text=display_title, font=("Segoe UI", 17, "bold"), wraplength=450).pack(padx=20, pady=(20, 12))
        ctk.CTkLabel(self, text="File type").pack(anchor="w", padx=24)
        extensions = list(dict.fromkeys(c.extension.upper() for c in choices))
        self.extension = ctk.CTkOptionMenu(self, values=extensions, command=self.update_resolutions, width=450)
        self.extension.pack(padx=24, pady=(0, 10))
        ctk.CTkLabel(self, text="Resolution").pack(anchor="w", padx=24)
        self.resolution = ctk.CTkOptionMenu(self, values=[""], width=450)
        self.resolution.pack(padx=24, pady=(0, 10))
        ctk.CTkLabel(self, text="Only available formats are listed. Audio is included.", text_color="#abb8c4").pack(pady=5)
        buttons = ctk.CTkFrame(self, fg_color="transparent")
        buttons.pack(pady=12)
        ctk.CTkButton(buttons, text="Cancel", fg_color="#536171", command=lambda: self.finish(None)).pack(side="left", padx=5)
        ctk.CTkButton(buttons, text="Download", command=self.download).pack(side="left", padx=5)
        self.update_resolutions(extensions[0])
        self.protocol("WM_DELETE_WINDOW", lambda: self.finish(None))
        self.after(100, self.lift)

    def update_resolutions(self, extension):
        values = [f"{c.height}p" for c in self.choices if c.extension.upper() == extension]
        self.resolution.configure(values=values)
        self.resolution.set(values[0])

    def download(self):
        choice = next(c for c in self.choices if c.extension.upper() == self.extension.get() and f"{c.height}p" == self.resolution.get())
        self.finish(choice)

    def finish(self, choice):
        if not self.finished:
            self.finished = True
            self.complete(choice)
            self.destroy()
