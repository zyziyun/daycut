# Why the second request is faster (synthetic example, short format)

## HOOK
    You ask a chatbot the same question twice. The second answer comes back faster. The difference can be ten times.

## BODY
    Here's what's going on. The first time, the model does all the work from scratch, and that work is called inference. Inference is the part you pay for every single day. The second time, a cache has already stored most of that work. The cache keeps the answer close so nobody waits. So the server skips the slow part and goes straight to the end.

## INSIGHT
    And here's the detail I don't see explained enough. The speed-up isn't really about the model at all. It's about memory, because reading a stored result is cheaper than computing it again. Throughput tells you how many requests finish each second, and caching moves that number more than a bigger chip does.

## CLOSE
    That's the lens I keep coming back to whenever something feels instant. I ask what was computed earlier and kept around. Most of the time, fast just means remembered.
