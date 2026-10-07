"""Everyday English words, for the caption glossary / proofread guards (``vstudio.proofread``).

A recurring ASR confusion is a rare token or a non-word (Hibrid, trunking, RM); a word the speaker says all the
time in normal use (part, make, after, client side) is never one, however much it "sounds like" a glossary term.

    from vstudio import en_common as EN
    EN.is_function("and")              # True: and / or / the / a / to ... never swapped or propagated on their own
    EN.is_common("parts")              # True: inflections of a common word count too
    EN.all_common("client side")       # True: every latin word of the span is common
    EN.english_text(transcript)        # True: English speech (vs English terms inside Chinese speech)
"""
import re

FUNCTION = frozenset("""
a an the and or but nor so yet if then than as of at by for from in into on onto off out over under up down to
with without within about above across after against along among around before behind below beneath beside
besides between beyond during except inside near since through throughout till toward towards until upon via
is am are was were be been being do does did done have has had having will would shall should can could may might
must ought i me my mine myself you your yours yourself yourselves he him his himself she her hers herself it its
itself we us our ours ourselves they them their theirs themselves this that these those who whom whose which what
whatever whichever whoever when where why how there here not no yes all any both each either neither every few
many more most much other others some such own same just also too very only even still again ever never now
once twice already ok okay oh um uh yeah well like
""".split())

COMMON = frozenset("""
able accept access account across act action active actually add address admin after afternoon again age ago
agree ahead air allow almost alone along already alright always amount and answer anybody anyone anything anyway
anywhere apart appear apply approach area argue arm around arrive art article ask attack attention available
avoid away back bad bag ball bank bar base basic basically bear beat beautiful because become bed begin
beginning behavior believe benefit best better big bill bit black block blue board body book born boss bottom
box boy break bring brother brown build building business busy buy call came camera car card care careful carry
case catch cause center certain certainly chair chance change character charge check child children choice
choose church city claim class clean clear clearly click client close code cold collect college color come
comment common company compare complete completely concern condition consider contain continue control cool copy
corner correct cost could count country couple course cover create cross cup current cut dad dark data date
daughter day dead deal dear death decide deep definitely degree depend describe design detail develop die
difference different difficult dinner direction directly discuss do doctor dog door double down draw dream
dress drink drive drop during early easy eat edge effect effort eight either else end enjoy enough enter entire
especially even evening event ever every everybody everyone everything exactly example except exist expect
experience explain eye face fact fail failure fall false family far fast father fear feel feeling few field
fight figure file fill final finally find fine finger finish fire first fit five fix floor fly follow food
foot force forget form forward four free friend front full fun function future game general get girl give glad
go goal gone good got great green ground group grow guess guy hair half hand handle happen happy hard
head health hear heart heavy hello help here hey high himself history hit hold holder home hope hot hour house
huge human hundred idea important include increase indeed information inside instead interest interesting
into issue item job join jump keep key kid kill kind kitchen knew know known land language large last late
later laugh lead learn least leave left leg less let letter level lie life light likely line list listen
little live local long look lose lot love low main make man manage many mark market matter maybe mean meaning
meet member memory mention message middle might mind minute miss model moment money month morning mother move
movie much music name national natural nature near nearly need never new news next nice night nine none normal
note nothing notice number obviously offer office often old once one online open option order original other
otherwise outside page paper parent part particular particularly party pass past pay people perfect perhaps
period person pick picture piece place plan play please point police poor popular position possible post power
practice prepare present pretty price print probably problem process produce product program project
property provide public pull purpose push put question quick quickly quite race raise random rate rather reach
read ready real really reason receive recent record red reduce remember remove repeat reply report request
require rest result return right road role room rule run safe same save saw say school second section see seem
self sell send sense serious serve service set seven several shall share short should show side sign
similar simple simply since single sir sister sit situation six size small social someone something sometimes
somewhere son soon sorry sort sound south space speak special spend stage stand start state stay step stop
store story street strong student study stuff style subject success suddenly support suppose sure system table
take talk task teacher team tell ten term test thank thanks thing think third thousand three through throw
time today together tomorrow tonight top total touch toward town track trade travel tree trouble true trust try
turn twenty two type under understand unit until use used useful user usually value various version video view
visit voice wait walk wall want war watch water way week weekend weight welcome west whatever whether white
whole wife win window wish woman wonder word work world worry worth write wrong year yesterday young zero
""".split()) | FUNCTION

_WORD = re.compile(r"[A-Za-z][A-Za-z']*")


def _bases(w):
    """``w`` and its likely stems (parts -> part, making -> make, failures -> failure, holders -> holder)."""
    w = w.lower().replace("'s", "")
    out = [w]
    for suf, add in (("ies", "y"), ("es", ""), ("s", ""), ("ing", ""), ("ing", "e"), ("ed", ""), ("ed", "e"),
                     ("er", ""), ("ly", "")):
        if w.endswith(suf) and len(w) - len(suf) >= 3:
            out.append(w[:-len(suf)] + add)
    return out


def _acronym(w):
    return len(w) >= 2 and w.isupper()


def is_function(w):
    return not _acronym(w) and w.lower() in FUNCTION


def is_common(w):
    """A word said all the time in normal speech (inflections included); acronyms (IT, US, RM) never are."""
    return not _acronym(w) and any(b in COMMON for b in _bases(w))


def latin_words(span):
    return _WORD.findall(span or "")


def all_common(span):
    """True when ``span`` is latin words only and every one of them is common (part, client side, service here)."""
    ws = latin_words(span)
    return bool(ws) and not re.search(r"[0-9㐀-鿿]", span) and all(is_common(w) for w in ws)


def english_text(text):
    """True when ``text`` is English speech (latin words outnumber CJK characters 4:1). Its ASR spells everyday
    words correctly, so the sound-alike respellings meant for English terms inside Chinese speech (派篮 ->
    pipeline, Rewanking -> reranking) never apply to its plain lowercase words."""
    words = len(latin_words(text))
    cjk = len(re.findall(r"[㐀-鿿豈-﫿]", text or ""))
    return words > 0 and words >= 4 * cjk


def all_function(span):
    ws = latin_words(span)
    return bool(ws) and not re.search(r"[0-9㐀-鿿]", span) and all(is_function(w) for w in ws)


__all__ = ["FUNCTION", "COMMON", "is_function", "is_common", "all_common", "all_function", "latin_words", "english_text"]
