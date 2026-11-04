"""오늘의 한마디 생성기 (직접 쓴 한글/영어 문장 조합).

- SINGLES: 완성된 한 문장 59개.
- 조합: (상황 A) + (다독이는 말 B) + (마무리 C). A·B·C는 어떤 짝으로 합쳐도 말이 되도록 쓴 문장 조각이다.
  64 × 80 × 12 = 61,440가지. SINGLES와 합치면 61,499가지 → 하루 하나씩 약 168년 동안 겹치지 않는다.
- 날짜(일 수)마다 서로소 간격으로 건너뛰어 고르므로, 연달아 나오는 문장끼리 비슷하지 않고 TOTAL일 동안 같은 문장이 반복되지 않는다.
- 새 문장 조각을 더하려면 아래 목록 끝에 한 줄을 추가하면 된다(형식: 한글|English). 개수가 바뀌면 STRIDE가 서로소인지 시험이 확인해 준다.
"""
from __future__ import annotations

SINGLES = (
    ("오늘 하루, 작은 한 걸음이면 충분해요.", "One small step is enough for today."),
    ("당신의 속도는 틀리지 않았어요.", "Your pace is not wrong."),
    ("오늘도 당신만의 방식으로 빛나면 돼요.", "Shine today in your own way."),
    ("시작하는 용기가 이미 절반의 성공이에요.", "The courage to begin is already half the work."),
    ("어제의 나보다 조금만 다정하게 시작해요.", "Start today a little kinder than yesterday."),
    ("좋은 일은 천천히, 그러나 분명히 오고 있어요.", "Good things are arriving, slowly but surely."),
    ("오늘의 작은 시도가 내일의 큰 길이 돼요.", "Today's small attempt becomes tomorrow's wide road."),
    ("서두르지 않아도 도착할 곳에는 도착해요.", "You don't have to rush to arrive where you're headed."),
    ("완벽하지 않아도 괜찮아요. 시작이 중요해요.", "It doesn't have to be perfect. Starting is what matters."),
    ("오늘 만나는 모든 순간에 호기심을 가져 봐요.", "Meet every moment today with curiosity."),
    ("당신의 창작은 세상에 꼭 필요한 이야기예요.", "What you create is a story the world needs."),
    ("숨을 깊게 쉬고, 천천히 시작해 봐요.", "Take a deep breath and begin slowly."),
    ("오늘은 나를 믿어 주는 날로 해요.", "Let today be a day you trust yourself."),
    ("작은 기쁨 하나를 찾는 하루가 되길 바라요.", "May you find one small joy today."),
    ("실수해도 괜찮아요. 거기서 새로운 길이 열려요.", "Mistakes are okay. New paths open from them."),
    ("지금 있는 그 자리에서 충분히 잘하고 있어요.", "You're doing well right where you are."),
    ("오늘의 햇살은 오직 오늘만 비춰요. 마음껏 누려요.", "Today's light shines only today. Enjoy it."),
    ("하고 싶은 일을 향해 한 가지만 해 보세요.", "Do just one thing toward what you want."),
    ("당신 안에는 아직 꺼내지 않은 아이디어가 많아요.", "There are many ideas in you not yet brought out."),
    ("느리게 가도 멈추지 않으면 괜찮아요.", "Going slowly is fine as long as you keep going."),
    ("오늘은 어제보다 한 뼘 더 자유로워요.", "Today you are a little freer than yesterday."),
    ("마음이 가는 쪽으로 한 발만 내디뎌 봐요.", "Take one step toward what your heart leans to."),
    ("당신의 시선은 세상을 새롭게 보게 해요.", "Your way of seeing helps the world look new."),
    ("오늘의 걱정은 오늘의 나보다 작아요.", "Today's worries are smaller than today's you."),
    ("차분히 시작하면 하루가 부드럽게 흘러가요.", "Begin calmly and the day flows gently."),
    ("당신은 이미 많은 것을 해냈어요. 오늘도 해낼 거예요.", "You've already done so much. You'll do it again today."),
    ("작은 친절 하나가 하루를 바꿔요.", "One small kindness can change a day."),
    ("오늘은 잘 쉬는 것도 중요한 일이에요.", "Resting well is important work too."),
    ("떠오르는 생각을 믿고 한 줄 적어 봐요.", "Trust the thought that arises and jot down a line."),
    ("아침이 와서 다시 시작할 수 있다는 건 선물이에요.", "That morning comes and you can begin again is a gift."),
    ("당신의 꾸준함은 조용하지만 강한 힘이에요.", "Your steadiness is quiet but strong."),
    ("오늘 할 수 있는 만큼만, 마음을 다해서.", "Do what you can today, with your whole heart."),
    ("좋은 하루는 좋은 마음에서 시작돼요.", "A good day begins with a good heart."),
    ("당신이 만드는 모든 선은 당신만의 목소리예요.", "Every line you make is your own voice."),
    ("바람이 불어도 나는 내 길을 갈 수 있어요.", "Even when the wind blows, I can walk my own path."),
    ("오늘도 세상은 당신의 색을 기다리고 있어요.", "The world is waiting for your colors today."),
    ("괜찮아요, 천천히 해도 돼요.", "It's okay. You can take your time."),
    ("한 번 웃고 시작하면 하루가 가벼워져요.", "Start with one smile and the day feels lighter."),
    ("지금의 노력은 반드시 어딘가에 쌓이고 있어요.", "Your effort now is surely adding up somewhere."),
    ("오늘 하루도 당신답게, 충분히 멋지게.", "Be yourself today, and that is wonderful enough."),
    ("새로운 하루는 새로운 가능성이에요.", "A new day is a new possibility."),
    ("마음에 여백을 두면 좋은 생각이 들어와요.", "Leave space in your mind and good ideas will come in."),
    ("할 수 있다는 믿음이 첫 번째 재료예요.", "Believing you can is the first ingredient."),
    ("오늘 만나는 사람에게 따뜻한 말 한마디를 건네 봐요.", "Offer one warm word to someone you meet today."),
    ("당신의 하루는 당신이 그리는 한 장의 그림이에요.", "Your day is a picture you are painting."),
    ("조금 흔들려도 괜찮아요. 균형은 움직이며 찾는 거예요.", "A little wobble is fine. Balance is found in motion."),
    ("오늘의 나에게 수고했다고 미리 말해 줘요.", "Tell today's you 'well done' in advance."),
    ("가장 좋은 작품은 아직 만들어지지 않았어요.", "Your best work hasn't been made yet."),
    ("어떤 날에도 당신의 가치는 그대로예요.", "Your worth stays the same on any day."),
    ("깊은 숨 한 번, 가벼운 마음 한 번.", "One deep breath, one lighter heart."),
    ("오늘도 힘차게, 하지만 다정하게.", "Be strong today, and gentle too."),
    ("꿈은 매일 조금씩 가까워지고 있어요.", "Your dream gets a little closer every day."),
    ("당신이 오늘 보는 풍경이 누군가의 영감이 될 거예요.", "What you see today may inspire someone."),
    ("지금 이 순간도 충분히 아름다워요.", "This very moment is beautiful enough."),
    ("용기는 크지 않아도 돼요. 한 뼘이면 돼요.", "Courage needn't be big. An inch is enough."),
    ("오늘도 호기심 하나를 주머니에 넣고 나가요.", "Step out today with one curiosity in your pocket."),
    ("힘들면 잠깐 쉬어가요. 길은 그대로 있어요.", "If it's hard, pause. The road will still be there."),
    ("당신은 생각보다 훨씬 잘 해내고 있어요.", "You're doing much better than you think."),
    ("좋은 하루 보내세요. 당신은 그럴 자격이 있어요.", "Have a good day. You deserve it."),
)

def _pairs(raw: str) -> tuple[tuple[str, str], ...]:
    out = []
    for line in raw.strip("\n").split("\n"):
        ko, _, en = line.partition("|")
        out.append((ko.strip(), en.strip()))
    return tuple(out)


_A = _pairs("""아침이 조금 무겁게 느껴져도|Even if the morning feels a little heavy
할 일이 산더미처럼 쌓여 있어도|Even with a mountain of things to do
아직 아무것도 시작하지 못했어도|Even if you haven't started anything yet
마음이 어수선한 날에도|Even on a day when your mind is scattered
생각대로 되지 않는 날에도|Even on days when things don't go as planned
잠이 부족한 아침에도|Even on a morning short on sleep
비가 오는 날에도|Even on a rainy day
하늘이 잔뜩 흐려도|Even when the sky is thick with clouds
어제의 실수가 마음에 남아 있어도|Even if yesterday's mistake lingers
자신감이 조금 부족해도|Even if your confidence is running low
길이 아직 잘 보이지 않아도|Even if the road isn't clear yet
아무도 알아주지 않는 것 같아도|Even if it seems no one notices
나도 모르게 남과 비교하게 되어도|Even when you catch yourself comparing with others
작업이 막혀 있는 것 같아도|Even when your work feels stuck
영감이 떠오르지 않는 날에도|Even on a day with no inspiration
하루가 길게 느껴져도|Even if the day feels long
마음이 급해질 때에도|Even when you feel rushed
결과가 아직 보이지 않아도|Even if results aren't visible yet
몸과 마음이 지친 날에도|Even on a day when body and mind are tired
계획이 틀어져도|Even when plans fall apart
걱정이 자꾸 떠올라도|Even if worries keep coming up
혼자라고 느껴지는 순간에도|Even in moments when you feel alone
새로운 도전 앞에서 떨려도|Even if you tremble before a new challenge
시작하는 것이 두려워도|Even if beginning feels scary
오늘이 평범한 하루처럼 보여도|Even if today looks like an ordinary day
알람 소리가 야속하게 느껴져도|Even if the alarm clock sounds unkind
어려운 결정을 앞두고 있어도|Even when a hard decision awaits
기대만큼 풀리지 않아도|Even if things aren't going as hoped
내가 느리다고 느껴져도|Even if you feel you're moving slowly
마음이 조금 지쳐 있어도|Even if your heart is a little worn
세상 소식이 어수선하게 들려도|Even when the news of the world sounds chaotic
바깥이 시끄러운 날에도|Even on a day when the world outside is noisy
작은 일에 마음이 흔들려도|Even if small things shake you
갈 길이 멀게 느껴져도|Even if the road ahead feels long
완성이 아직 멀어 보여도|Even if finishing seems far away
오늘 하루가 쉽지 않을 것 같아도|Even if today looks like it won't be easy
스스로가 낯설게 느껴지는 날에도|Even on days when you feel unlike yourself
바람이 찬 아침에도|Even on a cold, windy morning
마음에 먹구름이 낀 날에도|Even on a day with clouds in your heart
기운이 나지 않는 아침에도|Even on a morning when energy is low
손에 잡히는 게 없는 날에도|Even on a day when nothing seems to take hold
해낼 수 있을지 의심이 들어도|Even if you doubt whether you can do it
눈앞의 일이 너무 커 보여도|Even if the task before you looks too big
아무 의욕이 생기지 않아도|Even if motivation hasn't shown up
일이 자꾸 미뤄져도|Even if things keep getting postponed
마음처럼 몸이 따라 주지 않아도|Even if your body won't follow your heart
어제와 똑같은 하루가 시작되어도|Even if a day just like yesterday begins
마음이 복잡하게 얽혀 있어도|Even if your feelings are tangled
힘들다는 말이 먼저 나와도|Even if "it's hard" is the first thing you say
누군가의 말이 마음에 걸려도|Even if someone's words are weighing on you
눈에 띄는 변화가 없어 보여도|Even if no change is visible
오래 해 온 일이 지겹게 느껴져도|Even if long-held work feels dull
불안한 생각이 먼저 찾아와도|Even if anxious thoughts arrive first
마음이 자꾸 과거로 향해도|Even if your mind keeps drifting to the past
앞날이 막막하게 느껴져도|Even if the future feels uncertain
하고 싶은 일이 너무 많아 막막해도|Even if so much you want to do feels overwhelming
지금 있는 곳이 낯설게 느껴져도|Even if where you are feels unfamiliar
오늘 일정이 빽빽해도|Even with a packed schedule today
마음 놓고 쉴 틈이 없어도|Even without room to rest easy
완벽하게 해내지 못했다는 생각이 들어도|Even if you feel you didn't do it perfectly
조용한 아침이 외롭게 느껴져도|Even if a quiet morning feels lonely
해야 할 일 앞에서 주저하게 돼도|Even if you hesitate before what must be done
하루를 시작할 힘이 부족해도|Even if you lack the strength to start the day
조금 뒤처진 것 같아도|Even if you feel a little behind""")
_B = _pairs("""당신은 이미 충분히 잘하고 있어요|you are already doing well enough
한 걸음이면 충분해요|one step is enough
천천히 가도 괜찮아요|it's okay to go slowly
당신의 속도는 틀리지 않았어요|your pace is not wrong
오늘의 작은 시도가 내일의 길이 돼요|today's small attempt becomes tomorrow's road
당신 안에는 아직 꺼내지 않은 힘이 있어요|there is strength in you not yet drawn out
시작하는 용기가 이미 절반이에요|the courage to begin is already half the work
지금까지 해 온 노력은 사라지지 않아요|the effort you've made so far does not disappear
쉬어 가도 길은 그대로 있어요|the road will still be there if you rest
오늘의 당신도 충분히 소중해요|today's you is precious enough
숨 한 번 고르면 마음이 훨씬 가벼워져요|one deep breath makes the heart much lighter
좋은 생각은 여백에서 찾아와요|good ideas arrive in empty spaces
작은 기쁨 하나는 분명 만날 수 있을 거예요|you will surely meet one small joy
당신만의 시선은 세상에 꼭 필요해요|your own way of seeing is needed in the world
서두르지 않아도 필요한 곳에 닿아요|you will reach where you need to be without rushing
오늘은 나에게 조금 더 다정해져도 좋아요|you may be a little kinder to yourself today
실수는 새로운 길을 알려 주는 표지판이에요|a mistake is a signpost to a new path
당신의 꾸준함은 조용하지만 강한 힘이에요|your steadiness is a quiet but strong power
한 줄만 적어도 하루는 움직이기 시작해요|even one written line gets the day moving
지금 이 순간에도 무언가가 자라고 있어요|something is growing even right now
완벽하지 않아도 시작할 자격이 있어요|you don't have to be perfect to begin
당신의 이야기는 아직 쓰이는 중이에요|your story is still being written
오늘의 걱정은 오늘의 당신보다 작아요|today's worries are smaller than today's you
좋은 일은 천천히, 그러나 분명히 오고 있어요|good things are coming, slowly but surely
당신이 만드는 모든 선은 당신의 목소리예요|every line you make is your own voice
한 번 웃으면 하루가 조금 가벼워져요|one smile makes the day a little lighter
오늘 만나는 순간마다 배울 것이 있어요|every moment today has something to teach
마음이 가는 쪽으로 한 발만 내디뎌 봐요|take just one step toward where your heart leans
당신은 생각보다 훨씬 멀리 와 있어요|you have come much farther than you think
지금의 노력은 어딘가에 차곡차곡 쌓이고 있어요|your effort now is adding up somewhere
내일의 당신이 오늘의 당신에게 고마워할 거예요|tomorrow's you will thank today's you
오늘은 새로운 가능성으로 가득해요|today is full of new possibilities
호기심 하나만 있으면 하루는 흥미로워져요|with a single curiosity the day becomes interesting
당신의 색은 당신만 낼 수 있어요|only you can make your color
잠깐 멈춰도 괜찮아요|it's fine to pause for a moment
느리게 가도 멈추지 않으면 돼요|going slowly is fine as long as you don't stop
가장 좋은 작품은 아직 만들어지지 않았어요|your best work hasn't been made yet
당신은 혼자가 아니에요|you are not alone
오늘의 한 걸음이 큰 변화의 시작이에요|today's step is the start of a big change
괜찮아요, 정말 괜찮아요|it's okay, truly okay
마음을 다하면 그것으로 충분해요|giving your whole heart is enough
당신의 하루에는 분명 빛나는 순간이 있어요|your day surely holds a shining moment
작게 시작해도 괜찮아요|it's fine to start small
오늘도 당신다운 하루를 만들 수 있어요|you can make a day that is truly yours again today
지금의 흔들림은 균형을 찾는 과정이에요|this wobble is part of finding balance
당신이 건네는 따뜻한 말 한마디가 누군가의 하루를 바꿔요|one warm word from you can change someone's day
오늘 하루를 믿어 봐도 좋아요|you can trust this day
당신의 노력은 반드시 어떤 모습으로든 돌아와요|your effort will return in some form
마음의 속도에 맞춰 걸어도 돼요|you can walk at the pace of your heart
그 자리에서도 당신은 충분히 아름다워요|you are beautiful enough right where you are
작은 변화가 큰 흐름을 만들어요|small changes create big currents
오늘의 햇살은 당신 몫이에요|today's sunlight is yours
잘 해내지 않아도 괜찮아요, 해 보는 것이 중요해요|you needn't do it perfectly; trying is what matters
어제보다 한 뼘 더 자라 있을 거예요|you will have grown a little more than yesterday
당신의 마음에는 이미 답이 있어요|your heart already holds an answer
조금씩 나아가는 것도 분명한 전진이에요|moving forward little by little is still real progress
오늘 흘린 땀방울이 내일의 자랑이 될 거예요|today's sweat will become tomorrow's pride
자신을 믿는 만큼 길이 열려요|the road opens as far as you believe in yourself
가끔은 돌아가는 길이 더 아름다워요|a roundabout path is sometimes more beautiful
당신의 존재만으로도 누군가에게 힘이 돼요|your presence alone gives someone strength
지금 이 순간도 충분히 아름다워요|this very moment is beautiful enough
오늘도 멋진 한 장면을 그려낼 수 있어요|you can paint one wonderful scene again today
불안은 지나가고 당신은 남아요|the worry will pass, and you will remain
천천히 숨 쉬면 답이 보이기 시작해요|breathe slowly and the answer begins to show
하루의 끝에는 분명 작은 성취가 기다리고 있어요|a small achievement is waiting at the end of the day
당신은 오늘도 누군가의 영감이에요|you are someone's inspiration today too
부드럽게 시작하면 하루도 부드럽게 흘러가요|begin gently and the day flows gently
당신이 있으니 오늘은 괜찮은 하루가 될 거예요|with you in it, today will be a good day
마음 한쪽에 여백을 남겨 두세요, 좋은 것이 들어올 자리예요|keep a little space in your heart, a place for good things to enter
오늘 필요한 만큼의 용기는 이미 가지고 있어요|you already have as much courage as you need today
당신의 하루는 한 장의 그림처럼 조금씩 채워져요|your day fills in little by little like a painting
지금 느끼는 감정도 소중한 재료예요|the feelings you have now are valuable material
한숨 돌리고 나면 다시 걸을 힘이 생겨요|after a breather, the strength to walk again returns
당신은 오늘도 성장하고 있어요|you are growing today too
완벽한 때를 기다리지 않아도 돼요|you don't have to wait for the perfect moment
마음 가는 대로 한 가지만 해 봐요|do just one thing your heart points to
기운이 나지 않아도 괜찮아요, 천천히 채우면 돼요|it's fine if energy is low, fill it up slowly
오늘의 당신은 어제보다 조금 더 단단해요|today's you is a little sturdier than yesterday's
길 위의 모든 순간이 작품의 일부예요|every moment on the road is part of the work
지금처럼 하나씩 하면 충분해요|doing things one at a time, as you are, is enough""")
_C = _pairs("""|
오늘도 잘 해낼 거예요.|You'll do great today.
오늘도 응원할게요.|Cheering for you today.
좋은 하루 보내요.|Have a good day.
오늘도 파이팅!|You've got this today!
당신의 하루를 응원해요.|Rooting for your day.
잘 다녀와요.|Go well.
오늘도 함께 걸어요.|Let's walk together today.
천천히, 그러나 힘차게.|Slowly, but with strength.
오늘의 당신에게 박수를!|Applause for today's you!
언제나 당신 편이에요.|Always on your side.
행복한 하루 되세요.|Wishing you a happy day.""")

COMBOS = len(_A) * len(_B) * len(_C)
TOTAL = len(SINGLES) + COMBOS
STRIDE = 7919   # 소수. TOTAL과 서로소여야 모든 날이 겹치지 않는다(시험에서 확인)


def message_for(day_number: int) -> dict:
    """day_number(예: date.toordinal())에 해당하는 {"ko": ..., "en": ...} 한마디."""
    idx = (day_number * STRIDE) % TOTAL
    if idx < len(SINGLES):
        ko, en = SINGLES[idx]
        return {"ko": ko, "en": en}
    idx -= len(SINGLES)
    c, rest = idx % len(_C), idx // len(_C)
    b, a = rest % len(_B), rest // len(_B)
    (ka, ea), (kb, eb), (kc, ec) = _A[a], _B[b], _C[c]
    ko = f"{ka}, {kb}." + (f" {kc}" if kc else "")
    en = f"{ea}, {eb}." + (f" {ec}" if ec else "")
    return {"ko": ko, "en": en}
