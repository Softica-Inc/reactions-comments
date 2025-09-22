import os
from dotenv import load_dotenv

# Load env file when running locally
load_dotenv()

# Bot credentials
BOT_NAME = os.getenv("BOT_NAME")
BOT_TOKEN = os.getenv("BOT_TOKEN")
API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH")

# Paths
DB_FILE = os.getenv("DB_FILE", "bot_data.db")
LOGS_DIR = os.getenv("LOGS_DIR", "../logs")
ZIP_RAR_DIR = os.getenv("ZIP_RAR_DIR", "zip_files")
EXTRACT_BASE_DIR = os.getenv("EXTRACT_BASE_DIR", "extracted_sessions")
PROXY_FILE = os.getenv("PROXY_FILE", "proxies.json")

# General settings
DELAY_BETWEEN_ACCOUNTS = int(os.getenv("DELAY_BETWEEN_ACCOUNTS", "20"))
ACCOUNTS_PER_PAGE = int(os.getenv("ACCOUNTS_PER_PAGE", "10"))
BUTTONS_PER_ROW = int(os.getenv("BUTTONS_PER_ROW", "2"))
REACTION_DELAY_MIN = float(os.getenv("REACTION_DELAY_MIN", "1.3"))
REACTION_DELAY_MAX = float(os.getenv("REACTION_DELAY_MAX", "3.1"))
MAX_COMMENTING_ACCOUNTS = int(os.getenv("MAX_COMMENTING_ACCOUNTS", "10"))
COMMENT_COUNT = int(os.getenv("COMMENT_COUNT", "20"))
CLIENT_CONNECTION_TIMEOUT = int(os.getenv("CLIENT_CONNECTION_TIMEOUT", "10"))
MAX_RECONNECT_ATTEMPTS = int(os.getenv("MAX_RECONNECT_ATTEMPTS", "3"))
# COMMENT_DELAY_MIN = float(os.getenv("COMMENT_DELAY_MIN", "5.3"))
# COMMENT_DELAY_MAX = float(os.getenv("COMMENT_DELAY_MAX", "9.6"))
COMMENT_DELAY_MIN = 20.3
COMMENT_DELAY_MAX = 50.6

# Rate limits
GLOBAL_RATE_LIMIT = int(os.getenv("GLOBAL_RATE_LIMIT", "5"))
VIEW_ACCOUNTS_MIN = int(os.getenv("VIEW_ACCOUNTS_MIN", "8"))
VIEW_ACCOUNTS_MAX = int(os.getenv("VIEW_ACCOUNTS_MAX", "10"))

# Static constants
INVITE_LINK, CHAT_ID, AUTO_CHAT_ID, AUTO_REACTION, REACTION_INPUT, UNSUB_CHANNEL_ID, PROXY_TYPE, PROXY_DETAILS, AUTO_COMMENTS = range(9)

DEFAULT_COMMENTS = [
    "Great post!",
    "Love this!",
    "Awesome content!",
    "Keep it up!",
    "Nice one!"
]


PPLX_API_KEY = os.getenv("PPLX_API_KEY")

# Vocabulary for comments in different languages
COMMENT_VOCABULARY = {
    "English": [
        # --- Початкові ---
        "Thank you very much", "Huge thanks", "I appreciate you", "I am very grateful",
        "Thanks for your help", "You really helped me", "I found everything I was looking for",
        "I solved all my problems", "I’m glad I found this channel", "This really helped me",
        "I am very thankful", "Your advice is priceless", "I appreciate your support",
        "I couldn’t have done it without you", "This is exactly what I needed",
        "Now I have no problems", "You made my day better", "Thanks for the clarification",
        "You’re a true professional", "Thank you for your patience", "This channel is a real find",
        "You helped me tremendously", "I am very satisfied", "Thanks for the great content",
        "Now everything is clear", "I didn’t expect such help", "Everything became easier with you",
        "That was the best advice", "You made my life easier", "I’m so glad I found this",
        "Now everything works", "This is the best information", "Thanks for the detailed explanation",
        "I’m so grateful", "This is exactly what I was looking for", "Now everything is clear to me",
        "Thank you, you’re the best", "That was very helpful", "I found all the answers here",
        "Thanks for the support", "You made the task easier for me",
        "Everything turned out to be easier than I thought", "Thanks for the professional approach",
        "I’m very satisfied with the result", "Thank you for the useful information",
        "This is exactly what I needed",

        # --- Додаткові унікальні ---
        "Your help exceeded my expectations", "I truly appreciate your dedication",
        "I’m impressed with your expertise", "This solved my issue instantly",
        "Such a valuable piece of advice", "You went above and beyond",
        "Everything makes perfect sense now", "You saved me so much time",
        "This was explained perfectly", "I learned something new today",
        "Your support means a lot to me", "Thanks for being so responsive",
        "You made it simple and clear", "I feel much more confident now",
        "You turned a hard task into an easy one", "I appreciate the quick response",
        "Such clarity is rare, thank you", "That was incredibly useful",
        "You made the complex seem simple", "I can finally move forward now",
        "Your guidance was spot on", "It’s a relief to have this answer",
        "Thanks for going into detail", "You’ve been a huge help today",
        "I never thought I’d solve this so fast", "Your explanation is crystal clear",
        "You’ve been incredibly kind", "I’ll definitely recommend you to others",
        "Your professionalism stands out", "I’m impressed by your patience",
        "You understood exactly what I needed", "This is beyond helpful",
        "I’m so relieved right now", "This advice is pure gold",
        "You have made everything straightforward", "I couldn’t have asked for better help",
        "You’ve made my day so much easier", "Everything is working perfectly now",
        "This was exactly the answer I was hoping for", "I’m grateful for your expertise",
        "You always know the right solution", "I truly value your time and effort",
        "I’m amazed by how quickly you solved this", "You’ve been an absolute lifesaver",
        "You made a difficult problem disappear", "I’ll remember this advice for the future",
        "This is more than I expected", "Thanks for understanding my situation",
        "You’ve been extremely thorough", "You’re incredibly good at what you do",
        "I couldn’t be happier with the result", "This is the kind of help everyone needs",

        # --- Нові, щоб довести до 250+ ---
        "Your guidance was a game changer", "I really admire your approach",
        "That was quick and efficient", "Your assistance was exceptional",
        "I appreciate your attention to detail", "You made this process smooth",
        "This exceeded my hopes", "You’re incredibly resourceful",
        "Your answer gave me clarity", "That saved me a lot of stress",
        "I feel so much better now", "Your advice worked perfectly",
        "This is an amazing solution", "I’m glad I asked you",
        "I couldn’t have done it better myself", "You handled this brilliantly",
        "Your kindness doesn’t go unnoticed", "That explanation hit the mark",
        "I feel supported and understood", "You delivered exactly what I needed",
        "Your input was essential", "This was a top-notch answer",
        "You turned confusion into clarity", "Your skill is impressive",
        "That’s the most helpful reply I’ve seen", "You completely solved my confusion",
        "Your response was lightning fast", "This information is incredibly valuable",
        "You made the impossible possible", "That was a perfect breakdown",
        "You’ve got a real talent for explaining", "You found a simple path through complexity",
        "Your advice just saved my project", "I’m very pleased with your help",
        "You resolved all my doubts", "This worked on the first try",
        "You’ve got such a helpful attitude", "I’m amazed at the detail you provided",
        "You’ve really outdone yourself this time", "I feel more confident moving forward",
        "That was the clarity I needed", "You’ve been so patient with me",
        "This was an outstanding response", "Your support has been invaluable",
        "I feel like a weight has been lifted", "That was spot-on guidance",
        "You’ve given me a fresh perspective", "Your help makes a real difference",
        "That was a professional-level explanation", "I’m really impressed with your work",
        "You brought a smile to my face", "You gave me exactly the right push",
        "This solved a big problem for me", "Your approach is inspiring",
        "I’m grateful for the time you spent", "Your detailed answer was perfect",
        "That was exactly the fix I needed", "I’ll remember this trick next time",
        "Your clear thinking stands out", "You’ve helped me more than you know",
        "You’ve been a tremendous help", "This was handled flawlessly",
        "You’ve set a great example", "This was brilliant advice",
        "I really value your insights", "You have made my day brighter",
        "You’ve got a gift for problem-solving", "Your solution worked like a charm",
        "That was an eye-opening explanation", "You completely cleared things up",
        "This is a solution I can trust", "You always provide excellent advice",
        "I feel so much more informed", "Your help is second to none",
        "This turned out perfectly", "That explanation was flawless",
        "You took the time to make it right", "Your commitment is admirable",
        "This makes everything so much easier", "You’ve been incredibly generous with your help",
        "I couldn’t have asked for a better outcome", "You’ve got an impressive level of knowledge",
        "Your solution was exactly on target", "I’m thankful for your accuracy",
        "This gave me total peace of mind", "You always go the extra mile",
        "That was thorough and precise", "I’m so happy with the result",
        "This fixed everything instantly", "You’re fantastic at what you do"
    ]
}




# COMMENT_VOCABULARY = {
#     "Русский": [
#         "Спасибо большое", "Огромное спасибо", "Благодарю тебя", "Я очень признателен",
#         "Спасибо за помощь", "Ты мне очень помог", "Я нашел все что искал", "Я решил все проблемы",
#         "Я рад что увидел этот канал", "Это очень помогло мне", "Я очень благодарен",
#         "Твои советы бесценны", "Я ценю твою поддержку", "Без тебя я бы не справился",
#         "Это именно то что мне нужно", "Теперь у меня нет проблем", "Ты сделал мой день лучше",
#         "Спасибо за разъяснение", "Ты настоящий профессионал", "Благодарю за терпение",
#         "Этот канал просто находка", "Ты невероятно мне помог", "Я очень доволен",
#         "Спасибо за отличный контент", "Теперь все понятно", "Я не ожидал такой помощи",
#         "С тобой все стало проще", "Это был лучший совет", "Ты сделал мою жизнь проще",
#         "Я очень рад что нашел это", "Теперь у меня все работает", "Это лучшая информация",
#         "Спасибо за подробные объяснения", "Я так благодарен", "Это именно то что искал",
#         "Теперь мне все ясно", "Спасибо ты лучший", "Это было очень полезно",
#         "Я нашел здесь все ответы", "Спасибо за поддержку", "Ты облегчил мне задачу",
#         "Все оказалось проще чем я думал", "Спасибо за профессиональный подход",
#         "Я очень доволен результатом", "Благодарю за полезную информацию",
#         "Это именно то что мне было нужно"
#     ],
#     "Испанский": [
#         "Muchas gracias", "Mil gracias", "Te lo agradezco", "Estoy muy agradecido",
#         "Gracias por tu ayuda", "Me has ayudado mucho", "Encontré todo lo que buscaba",
#         "He resuelto todos mis problemas", "Me alegra haber encontrado este canal",
#         "Esto me ha ayudado mucho", "Estoy profundamente agradecido", "Tus consejos no tienen precio",
#         "Aprecio tu apoyo", "Sin ti no lo habría logrado", "Esto es justo lo que necesitaba",
#         "Ahora no tengo problemas", "Has mejorado mi día", "Gracias por la aclaración",
#         "Eres un verdadero profesional", "Gracias por tu paciencia", "Este canal es un verdadero hallazgo",
#         "Me has ayudado increíblemente", "Estoy muy contento", "Gracias por el excelente contenido",
#         "Ahora todo está claro", "No esperaba tanta ayuda", "Contigo todo es más fácil",
#         "Ese fue el mejor consejo", "Has hecho mi vida más fácil", "Estoy muy feliz de haberlo encontrado",
#         "Ahora todo me funciona", "Es la mejor información", "Gracias por las explicaciones detalladas",
#         "Estoy tan agradecido", "Esto es exactamente lo que buscaba", "Ahora todo tiene sentido para mí",
#         "Gracias eres el mejor", "Esto ha sido muy útil", "Aquí encontré todas las respuestas",
#         "Gracias por el apoyo", "Me facilitaste la tarea", "Todo fue más fácil de lo que pensaba",
#         "Gracias por tu enfoque profesional", "Estoy muy satisfecho con el resultado",
#         "Gracias por la información útil", "Esto es justo lo que necesitaba"
#     ],
#     "Узбекский": [
#         "Катта раҳмат", "Жудаям катта раҳмат", "Сенга миннатдорчилик билдираман", "Мен жуда миннатдорман",
#         "Ёрдаминг учун раҳмат", "Жуда катта ёрдам бердинг", "Излаганимни топдим", "Муаммоларим ҳал бўлди",
#         "Ушбу канални топганимдан хурсандман", "Бу менга жуда ёрдам берди", "Мен жуда миннатдорман",
#         "Сенинг маслаҳатларинг жуда қимматли", "Сенинг ёрдамингни қадрлайман", "Сенсиз эплай олмасдим",
#         "Бу менга айнан керак нарса", "Энди муаммоларим йўқ", "Бугунимни янада яхшиладинг",
#         "Тушунтирганинг учун раҳмат", "Сен ҳақиқий профессионалсан", "Сабринг учун раҳмат",
#         "Бу канал ҳақиқий топилма", "Сен менга жуда катта ёрдам бердинг", "Мен жуда хурсандман",
#         "Зўр контент учун раҳмат", "Энди ҳаммаси тушунарли", "Бунақа ёрдамни кутмагандим",
#         "Сен билан ҳамма нарса осонроқ", "Бу энг яхши маслаҳат эди", "Ҳаётимни осонлаштирдинг",
#         "Буни топганимдан жуда хурсандман", "Энди ҳаммаси ишлаяпти", "Бу энг яхши маълумот",
#         "Батафсил тушунтириш учун раҳмат", "Мен шунчалик миннатдорман", "Айнан шуни излагандим",
#         "Энди ҳаммаси тушунарли", "Раҳмат, сен энг зўр", "Бу жуда фойдали бўлди",
#         "Бу ерда барча жавобларни топдим", "Ёрдаминг учун раҳмат", "Вазифамни енгиллаштирдинг",
#         "Ҳаммаси ўйлаганимдан осонроқ бўлди", "Профессионал ёндашувинг учун раҳмат",
#         "Натижадан жуда хурсандман", "Фойдали маълумот учун раҳмат", "Айнан шу менга керак эди"
#     ],
#     "Арабский": [
#         "شكراً جزيلاً", "ألف شكر", "أشكرك", "أنا ممتن جداً",
#         "شكراً على مساعدتك", "لقد ساعدتني كثيراً", "وجدت كل ما كنت أبحث عنه",
#         "لقد حليت جميع مشاكلي", "أنا سعيد لأنني وجدت هذه القناة",
#         "لقد ساعدني هذا كثيراً", "أنا ممتن جداً", "نصائحك لا تقدر بثمن",
#         "أنا أقدر دعمك", "بدونك لما تمكنت من النجاح", "هذا بالضبط ما كنت أحتاجه",
#         "الآن لا توجد لدي مشاكل", "لقد جعلت يومي أفضل", "شكراً على التوضيح",
#         "أنت محترف حقيقي", "شكراً على صبرك", "هذه القناة اكتشاف حقيقي",
#         "لقد ساعدتني بشكل رائع", "أنا سعيد جداً", "شكراً على المحتوى الرائع",
#         "الآن كل شيء واضح", "لم أتوقع هذه المساعدة", "معك كل شيء أصبح أسهل",
#         "كان هذا أفضل نصيحة", "لقد سهلت حياتي", "أنا سعيد جداً لأنني وجدتها",
#         "الآن كل شيء يعمل", "هذه أفضل المعلومات", "شكراً على الشروحات المفصلة",
#         "أنا ممتن جداً", "هذا بالضبط ما كنت أبحث عنه", "الآن كل شيء أصبح واضحاً بالنسبة لي",
#         "شكراً أنت الأفضل", "لقد كان هذا مفيداً جداً", "لقد وجدت هنا جميع الإجابات",
#         "شكراً على الدعم", "لقد سهلت علي المهمة", "كل شيء كان أسهل مما كنت أعتقد",
#         "شكراً على منهجك المهني", "أنا راضٍ تماماً عن النتيجة", "شكراً على المعلومات المفيدة",
#         "هذا بالضبط ما كنت أحتاجه"
#     ]
# }

FREE_REACTIONS = {
    "❤️": "❤️",
    "👍": "👍",
    "🔥": "🔥",
    "🥰": "🥰",
    "👏": "👏",
    "🤔": "🤔",
    "🎉": "🎉",
    "🤩": "🤩",
    "🙏": "🙏",
    "👌": "👌",
    "🕊": "🕊",
    "😍": "😍",
    "🐳": "🐳",
    "❤️‍🔥": "❤️‍🔥",
    "💯": "💯",
    "⚡️": "⚡️",
    "🏆": "🏆",
    "🍓": "🍓",
    "🍾": "🍾",
    "💋": "💋",
    "👨‍💻": "👨‍💻",
    "👀": "👀",
    "😇": "😇",
    "🤝": "🤝",
    "✍️": "✍️",
    "🤗": "🤗",
    "🫡": "🫡",
    "🆒": "🆒",
    "💘": "💘",
    "😘": "😘",
    "😎": "😎"
}


# FREE_REACTIONS = {
#     "❤️": "❤️", "😊": "😊", "👍": "👍", "👊": "👊", "🥳": "🥳", "💔": "💔", "👏": "👏", "😂": "😂",
#     "👎": "👎", "🔥": "🔥", "😞": "😞", "🤓": "🤓", "😱": "😱", "🤬": "🤬", "🎉": "🎉", "🤩": "🤩",
#     "🤢": "🤢", "💩": "💩", "🙏": "🙏", "👌": "👌", "🕊️": "🕊️", "🤡": "🤡", "😘": "😘", "😻": "😻",
#     "🫶": "🫶", "🖤": "🖤", "💯": "💯", "⚡️": "⚡️", "🍌": "🍌", "🏆": "🏆", "💘": "💘", "😎": "😎",
#     "🍓": "🍓", "🍾": "🍾", "💋": "💋", "🖕": "🖕", "👿": "👿", "😢": "😢", "👻": "👻", "💻": "💻",
#     "👀": "👀", "🎃": "🎃", "🐒": "🐒", "🦄": "🦄", "😭": "😭", "✍️": "✍️", "🤗": "🤗", "😺": "😺",
#     "🎅": "🎅", "🎄": "🎄", "☃️": "☃️", "💅": "💅", "😜": "😜", "🗿": "🗿", "🆒": "🆒", "💕": "💕",
#     "🙈": "🙈", "🤷‍♂️": "🤷‍♂️", "🤦‍♀️": "🤦‍♀️", "😡": "😡", "🥰": "🥰"
# }