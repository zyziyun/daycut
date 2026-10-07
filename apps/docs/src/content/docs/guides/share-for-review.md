---
title: Share for review
description: Send a student, client or partner a review page for your clips. They approve each one or ask for a change, and their answers come back into your Inbox. Nothing is hosted or tracked.
---

Before you publish, someone else often needs to look: a student checking their own lesson clips, a client signing off a week of posts, a partner on a collab. **Share for review** makes a small web page they open in any browser. For each clip they see the video, its title, its platform versions and the post caption, and press **Approve** or **Request a change** with a comment. Their answers come back to you as Inbox items.

The page is a folder on your disk. Reelfold doesn't upload it, host it or track who opens it.

## What the reviewer gets

One folder, opened by double-clicking `index.html`:

```
Week-12-review-6a4d40/
├── index.html      the page: player, title, versions, caption, Approve / Request a change
├── review.json     the same data for machines (no file paths from your Mac)
├── media/          compressed previews (H.264, 540p / 720p / 1080p)
├── posters/        one poster per clip (the cover when there is one)
├── captions/       the post caption of each clip, as text
└── README.txt      how to open it
```

plus `Week-12-review-6a4d40.zip` next to it. The page works offline and makes no network requests. It has no analytics, fonts or scripts from anywhere else. Answers stay in the reviewer's browser until they send them.

## In the Mac app

1. Open the project and press **Share for review**. It's also on a clip's right-click menu, in the clip editor's top bar (the share icon), and on the delivery package screen.
2. Pick what to include: every finished clip is ticked; untick the ones you don't want reviewed.
3. Pick the **video quality**: Small (540p, quickest to send), Standard (720p, the default, fine on any phone) or High (1080p).
4. Optionally change the page title, add your name ("From …") and a note such as "Please reply by Friday".
5. **Made with Reelfold** at the bottom is on by default. It's a plain link to reelfold.com and you can switch it off. The page has no tracking either way.
6. Press **Make review page**. When it's done you see the folder and the zip, with **Reveal in Finder**.

### Privacy check

If the clips show other people, the dialog says so before anything is made: masked guests (call and podcast clips, privacy stickers you added in the editor), masks that don't cover every frame, guests who need to agree, hidden screen regions. When a warning applies you have to tick "everyone shown agreed to this review" before you can share. Masked previews are cut from the finished clips, so they keep the same masks.

## Getting answers back (no server)

On the page, the reviewer watches each clip, presses **Approve** or **Request a change**, writes what should change ("0:12 the caption covers my face"), adds their name and presses **Send my feedback**. They get three ways to send it to you:

- **Copy** a short feedback code (`RFB1.…`) and paste it into any chat;
- **Email**, which opens their mail app with a summary and the code;
- **Download file**, which saves a `.reelfold.json` they can attach.

In Reelfold, open the **Inbox** and press **Import feedback**. Paste the code, or the whole email (the code is found inside it, even if the mail app wrapped it across lines), or drop the `.reelfold.json` file on the dialog. Each answer becomes an Inbox item:

- **Approved** → one item with **Mark ready**. The clip shows as approved and is ready to schedule.
- **Change requested** → one item that opens the clip editor with the comment pinned on top. The comment also stays in the clip's chat, so you can ask the AI to make the change right there.

Importing the same feedback twice adds nothing. Undo on the Inbox toast takes a Mark ready back.

## Sharing the folder (your choice of host)

Reelfold never puts your clips online. To get the page to someone:

- **Send the zip** by chat, email or AirDrop. They unzip it and open `index.html`.
- **Upload the folder** to your own Google Drive, Dropbox or OneDrive and share that folder. Keep `index.html` next to `media/` and `posters/`. Most cloud drives preview videos but don't run web pages, so the reviewer should download the folder and open `index.html` locally.
- **Put it on your own website.** It's a static folder, so any static host works.

Shared pages don't expire on their own. When the review is done, delete the folder (and any uploaded copy).

## From the command line

```bash
python -m vstudio.project share --dir ~/Videos/week-12 --quality standard --title "Week 12" \
  --owner-name "Ziyun" --expiry-note "Please reply by Friday"      # --no-footer, --no-zip, --outputs a,b
python -m vstudio.project share --dir ~/Videos/week-12 --scan       # only the privacy warnings
python -m vstudio.project feedback import --file feedback-1a2b3c4d.reelfold.json   # or --text 'RFB1.…'
python -m vstudio.project feedback list --dir ~/Videos/week-12
python -m vstudio.project feedback resolve --dir ~/Videos/week-12 --id <item>      # approve -> ready
```

The same clips and options always give byte-identical output. The library is `vstudio.project.share` (`share`, `build_page`, `privacy_scan`, `parse_feedback`, `import_feedback`).

## Hosted review links (later)

A hosted link (upload with one click, answers arriving by themselves) is planned for a future studio plan. It will be opt-in. The local folder and the feedback code will keep working as they do now.
