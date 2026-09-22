# Corpus (Appendix)

This is the final, read-through-verified source corpus for the PSALM-SAGA evaluation, referenced as
an appendix from `EXPERIMENTAL_SETUP.md` / `EXPERIMENT_DRAFT.md` Section 2 ("Corpus / Dataset").
Every item below was read start to end to confirm it stands alone and closes cleanly.

**Where the files live** (in the `psalm-saga-experiments` repo):
- Full cleaned source texts: `data/cleaned/{english,dutch}/*.txt`
- Final selected story files (whole texts or excerpts, as used by the pipeline): `stories/{english,dutch}/*.txt`
- Machine-readable index: `stories/corpus.csv` — one row per item (id, language, genre_bucket,
  author, title, extraction method, source_file, path, word_count, char_count)

## Genre buckets

Five buckets, stratified 3 items per bucket per language, chosen so each stresses a different part
of the 36-dimension taxonomy:

- **Gothic / Supernatural** — strong, distinctive world-building and atmosphere; tests whether the
  spec can separate "eerie tone" (writing style) from "the rules of the haunting" (world-building).
- **Detective / Mystery** — plot structure and scene sequence are the most attributable dimensions
  here (clue placement, reveal ordering); character function (detective, red herring) is unusually
  schematic, stressing that sub-dimension specifically.
- **Domestic / Social Realism** — character-dense, low on overt world-building; the counterweight to
  the two plot-heavy buckets above.
- **Adventure / Sea or Travel** — strong scene sequence (episodic structure, journey staging) and
  clear world-building (geography, setting rules), with a different pacing profile than Detective's
  plot-driven pacing.
- **Satire / Moral Fable or Tale** — tests narrative voice most directly, via an intrusive
  commenting narrator.

## Length policy

Source items are used whole where they already fall within **1,200–4,000 words**. Longer works are
excerpted — a single chapter, a short contiguous run of chapters, or one self-contained tale from a
story collection — down to a ceiling of roughly **7,000 words (~41,000 characters)**. The corpus
favors narrative substance over brevity: public-domain candidates under about 2,000 words were rarely
substantial enough to instantiate all 36 sub-dimensions of the specification taxonomy. Each excerpt
was chosen because it reads as a complete scene or arc on its own, not because it happened to fall
under a word count.

## English — 15 items, all five buckets full

| Bucket | Author | Title | Selection & rationale | Words |
|---|---|---|---|---|
| Satire / Moral Fable | Oscar Wilde | The Happy Prince | Whole text. Strongly intrusive, moralizing fable narrator — the genre in its purest form. | 3,471 |
| Satire / Moral Fable | Jonathan Swift | A Modest Proposal | Whole text. The narrator's persona *is* the satirical mechanism. | 3,386 |
| Satire / Moral Fable | Mark Twain | The Celebrated Jumping Frog of Calaveras County | Whole text. Frame-narrator device makes the intrusive voice explicit. | 2,558 |
| Gothic / Supernatural | Edgar Allan Poe | The Fall of the House of Usher | Whole text. House-as-curse world-building set against tightly controlled, atmospheric prose. | 7,044 |
| Gothic / Supernatural | Charlotte Perkins Gilman | The Yellow Wallpaper | Whole text. The haunting may be psychological rather than supernatural — a useful ambiguous edge case for the taxonomy. | 6,078 |
| Gothic / Supernatural | M.R. James | Oh, Whistle, and I'll Come to You, My Lad | Whole text. Very explicit haunting mechanics played against dry, understated narration. | 7,944 |
| Detective / Mystery | G.K. Chesterton | The Blue Cross | Whole text. The detective function is inverted — the least competent-seeming character solves the case. | 7,470 |
| Detective / Mystery | Arthur Conan Doyle | A Scandal in Bohemia | Whole text. Textbook detective/client scaffolding with clean clue-reveal sequencing. | 8,521 |
| Detective / Mystery | Wilkie Collins | The Moonstone | Ch. XI. The novel is ~180k words; ch. XI is the theft night itself and reads as a complete "Act 1" — interrogations, the first suspicious behavior, the decision to call in outside help — closing on a deliberate cliffhanger. | 8,018 |
| Domestic / Social Realism | Elizabeth Gaskell | Cranford | Ch. I, "Our Society." The novel is episodic by design (~71k words total), so a single chapter is a genuine self-contained unit rather than an arbitrary cut; ch. I introduces the entire social world on its own. | 3,944 |
| Domestic / Social Realism | George Eliot | Silas Marner | Ch. I. A complete origin-story arc in one chapter — false accusation, betrayal by his closest friend and fiancée, exile. | 4,431 |
| Domestic / Social Realism | Jane Austen | Pride and Prejudice | Ch. XVIII, the Netherfield ball. The single richest character set-piece in the novel — Collins's disastrous dance, Elizabeth/Darcy friction, Wickham's conspicuous absence. | 5,169 |
| Adventure / Sea or Travel | Robert Louis Stevenson | Treasure Island | Ch. I–III combined. A genuine mini-arc: the captain's arrival, the Black Dog confrontation, delivery of the black spot, his death. | 6,615 |
| Adventure / Sea or Travel | Joseph Conrad | Typhoon | Ch. II. Builds Captain MacWhirr's defining trait (literal-minded refusal of "storm strategy") to a clean climax as the typhoon hits. | 5,609 |
| Adventure / Sea or Travel | Richard Henry Dana Jr. | Two Years Before the Mast | Ch. VI, "Loss of a Man." A complete dramatic episode — death at sea, the auction ritual, a superstition scene with real character payoff. | 2,064 |

Considered and not selected, once each bucket already had 3 strong fits: *Carmilla* and *Gulliver's
Travels* (Gothic/Satire spares — both have good excerptable chapters if a bucket ever needs a 4th);
*Narrative of Arthur Gordon Pym* ch. XIX–XX and *The Awakening* ch. VII+IX+X (Adventure/Domestic —
both fully verified as strong, displaced only because their buckets already had 3 picks).

## Dutch — 14 items. Detective/Mystery is 2, not 3 — see the gap note below.

| Bucket | Author | Title | Selection & rationale | Words |
|---|---|---|---|---|
| Satire / Moral Fable | J.J.A. Goeverneur | Fabelen en gedichtjes | Whole text. Classic verse-fable form; the moralizing narrator carries the piece. | 602 |
| Satire / Moral Fable | Heinrich Hoffmann | Piet de Smeerpoets, zijn berouw en bekeering | Whole text. Struwwelpeter-tradition cautionary tale — exaggerated comeuppance, intrusive moralizing narrator. | 894 |
| Satire / Moral Fable | J.J.A. Goeverneur | De ondeugende kinderen | Whole text. Same moral-fable tradition, children's misbehavior and consequence. | 2,165 |
| Gothic / Supernatural | Heinrich Hoffmann | Een aardig prentenboek met leerzame vertellingen | Whole text. Grotesque cautionary imagery bordering on the macabre. | 1,691 |
| Gothic / Supernatural | Heinrich Hoffmann | De vliegende Robert | Whole text. An explicit supernatural "rule" (play with an umbrella in a storm, get blown away forever) in miniature. | 300 |
| Gothic / Supernatural | J.J.A. Goeverneur | Vrouw Holle (from *Oude sprookjes*) | One of 8 independent tale retellings in the source collection, extracted individually. A portal-to-another-world fairy tale with explicit reward/punishment magic rules — the strongest "rules of the haunting" fit in the collection. | 1,159 |
| Detective / Mystery | Jacob van Lennep | De pleegzoon | Ch. 9. An afkomst-mysterie (concealed-birth mystery); this chapter is the narrator's own account of his hidden origin, closing on a genuine cliffhanger (a secret door opens as the chapter ends). | 5,307 |
| Detective / Mystery | Jacob van Lennep | De lotgevallen van Ferdinand Huyck | Ch. 11. A police informant's full backstory plus a live case briefing, culminating in a manhunt the narrator has concealed information about — genuinely schematic detective material embedded in an otherwise adventure novel. | 5,523 |
| Domestic / Social Realism | Reinoudina de Goeje | De kinderen van 't woud | Whole text. Character-dense domestic sketch, minimal world-building. | 5,316 |
| Domestic / Social Realism | Justus van Maurik | De ooievaar komt (from *Verspreide novellen*) | Final novella in the collection, extracted individually. A complete standalone sketch about a household awaiting a birth — no dependency on the rest of the collection. | 2,673 |
| Domestic / Social Realism | A.L.G. Bosboom-Toussaint | Majoor Frans | Opening span: the aunt's inheritance letter plus the first scene between the two male leads. The title character is introduced entirely by reputation before she ever appears — character-driven, near-zero world-building. | 6,671 |
| Adventure / Sea or Travel | J.J.A. Goeverneur | Reizen en avonturen van mijnheer Prikkebeen | Whole text. Episodic travel-adventure, fits the length target as-is. | 5,721 |
| Adventure / Sea or Travel | P.J. Andriessen | De Hollandsche Robinson Crusoë | Ch. 1. Classic Robinsonade; a complete shipwreck-to-landing arc. | 4,932 |
| Adventure / Sea or Travel | Jacob van Lennep | De lotgevallen van Ferdinand Huyck | Ch. 5. A complete danger-and-rescue arc (ambush, knife at the throat, twist reveal) — picaresque adventure register, distinct from ch. 11's detective register in the same novel. | 5,479 |

**Note on Van Lennep:** he supplies 3 of these 14 items — *De pleegzoon* plus *Ferdinand Huyck* twice
(different chapters, different buckets). Each excerpt is independently self-contained; the repetition
is a deliberate trade-off against a thin available pool of Dutch public-domain narrative fiction.

**Gap — Dutch Detective/Mystery has 2 items, not 3.** Ivans (Jakob van Schevichaven, d. 1935), the
founder of Dutch detective fiction and the obvious candidate for this slot, is not in the local DBNL
public-domain catalog (`data/titels_pd.csv` in the experiments repo — 4,974 texts with available
full text, checked by author name and pseudonym, no result). A full-catalog title search across terms
like `geheim, raadsel, moord, speur, detective, mysterie, misdaad, dief, spion, rechercheur` turns up
only 17th–19th century murder-ballad broadsides (factual crime street literature, not fiction) and
religious verse tragedies (Vondel, Oudaen) — no narrative detective fiction at all. DBNL's own
`genre` metadata column has no detective/mystery category to filter on either. This is a structural
gap in the available public-domain Dutch catalog. Resolving it would require a non-DBNL Dutch
public-domain source.
