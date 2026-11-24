# Interfeys dizayni — Liquid Glass

XADICHA interfeysi qorong'i "Liquid Glass" muhiti: chuqur fon, ustida qatlam-qatlam shaffof shisha panellar.
Asosiy diqqat markazida suhbat turadi. Har bir animatsiya backend'ning haqiqiy holatini ko'rsatadi, soxta faollik yo'q.

## Tokenlar

Barcha rang, material va harakat qiymatlari bitta joyda: `src/app/globals.css`.

| Token | Qiymat | Vazifasi |
|---|---|---|
| `--background` | `#070A12` | fon |
| `--surface` | `#0B1020` | chuqur sirt |
| `--glass` / `--glass-border` | `rgba(255,255,255,.055)` / `.12` | shisha material |
| `--primary` | `#7775FF` | binafsha — asosiy urg'u |
| `--secondary` | `#37D9F5` | elektr moviy — tinglash, bajarilgan qadam |
| `--blue` | `#4285FF` | bajarish |
| `--foreground` / `--muted-foreground` | `#F8FAFC` / `#9CAAC0` | matn |

Materiallar: `.glass` (asosiy panel), `.glass-strong` (navigatsiya, kapsula, modal), `.glass-subtle`
(panel ichidagi qatlam, qayta xiralashtirilmaydi), `.glass-active` (faol element yoritishi).
`backdrop-filter` bo'lmasa, deyarli to'q fon ishlatiladi. Sozlamalardagi "Kam shaffoflik"
(`.solid-ui`) va tizimdagi `prefers-reduced-transparency` / `prefers-contrast` shishani to'q sirtga almashtiradi.
`prefers-reduced-motion` yoqilgan bo'lsa, barcha takroriy animatsiyalar o'chadi.

## Komponentlar (`src/components/xadicha/`)

| Fayl | Komponent |
|---|---|
| `glass.tsx` | `GlassPanel`, `PanelTitle`, `GlassInput`, `GlassModal`, `Segmented` |
| `navigation.tsx` | `GlassNavigation` — ixcham/kengaytirilgan yon panel, telefonda pastki panel |
| `ai-orb.tsx` | `AIOrb` — shisha shar, 10 ta holat |
| `voice-control.tsx` | `VoiceControl` — orb tugmasi (mikrofon faqat backend'da) |
| `conversation.tsx` | `AssistantView`, suhbat, kapsula, aniqlashtirish, `TaskCard`, `CurrentTaskPanel` |
| `task-timeline.tsx` | `TaskTimeline` (jonli vaqt chizig'i), `TraceList` (bosqichlar vaqti) |
| `screen-context.tsx` | `ScreenView`, `ScreenSummary`, `CapChip` |
| `settings-view.tsx` | `SettingsView`, `LangSwitch` |
| `views.tsx` | Boshqaruv paneli, Tarix, Tadqiqot |

Holat mantiqi React'dan alohida va sinalgan: `src/lib/presence.ts` (orb holati, vaqt chizig'i qatorlari).

## Orb holatlari — faqat haqiqiy manbadan

| Holat | Manba | Ko'rinish |
|---|---|---|
| idle | hech narsa bajarilmayapti | tinch shisha, sekin nur |
| listening | `listening = recording` | moviy to'lqinlar, `mic_level` ga bog'liq ustunlar |
| processing | `listening = transcribing` | tez aylanuvchi moviy oqim |
| thinking | vazifa boshlangan, qadam yo'q | sekin binafsha oqim |
| executing | kamida bitta qadam | halqa: har segment — haqiqiy qadam (bajarildi / joriy / xato / rad) |
| speaking | `phase = speaking` | sokin to'lqin (TTS ovoz darajasi backend'dan kelmaydi, shuning uchun reaktiv emas) |
| awaiting | `phase = awaiting_confirmation` | sariq halqa |
| interrupted / error | vazifa `cancelled` / `failed` yoki API xatosi | 5 soniya sariq / qizil |
| offline | backend bilan aloqa yo'q | kulrang |

## Vaqt chizig'i

`timeline(task)` qatorlari: so'rov qabul qilindi → tushunish va rejalash → har bir qadam (bajarilmoqda /
tekshirilmoqda / tasdiqlandi / xato / rad etildi) → tasdiq kutilmoqda → yakun. Davomiylik faqat backend bergan
qiymatdan (`duration_ms`, `started_at`/`finished_at`); qiymat bo'lmasa ko'rsatilmaydi.

## Javob matni

Backend javobni bir yo'la yuboradi (oqim yo'q). Interfeys yangi kelgan haqiqiy matnni so'zma-so'z ochib ko'rsatadi
(≈1 s). Bu matnni o'zgartirmaydi; ekran o'quvchiga to'liq matn darhol beriladi, tiklangan tarix animatsiyasiz.

## Ekran tahlili

"Ekran holatini olish" tugmasi `POST /api/screen/snapshot` ni chaqiradi: faol ilova, oyna sarlavhasi, kichik
ko'rinish (640 px), OCR qatorlari va accessibility elementlari. Surat faqat javobda keladi, diskka yozilmaydi va
sahifadan chiqilganda yo'qoladi. Ruxsat bo'lmasa — sababi ko'rsatiladi. Avtomatik so'rov yo'q, faqat bosilganda.
