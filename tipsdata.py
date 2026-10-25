"""BarksBuds Tips: original, practical articles for dog owners in NYC, Long Island and Westchester.

Each article: slug, title, short (card title), desc (meta description, ~150 chars), cat, icon, minutes (read time),
updated (ISO date), vet (True adds the "ask your vet" note), body (trusted HTML written here, never user input).
Keep it warm, practical and non-polarizing; no medical claims beyond "watch for this, call your vet".
"""

UPDATED = "2026-10-24"

CATS = [("runs", "At the dog run"), ("health", "Health & seasons"), ("community", "Meetups & packs"), ("puppies", "Puppies & training")]
CAT_LABEL = dict(CATS)

TIPS = [
    dict(slug="dog-run-etiquette", cat="runs", icon="i-paw", minutes=4, vet=False,
         title="Dog run etiquette: the unwritten rules every regular knows",
         short="Dog run etiquette",
         desc="The friendly, unwritten rules of NYC, Long Island and Westchester dog runs: gates, leashes, toys, treats, poop and when to call it a day.",
         body="""
<p class="lede">Every dog run has its regulars, and the regulars all follow the same handful of unspoken rules. Learn them once and you'll be welcome at any run from Riverside Park to Christopher Morley Park.</p>
<h2>At the gate</h2>
<ul>
<li><strong>One gate at a time.</strong> Most runs have a double gate. Close the outer gate behind you before you open the inner one, so nobody slips out.</li>
<li><strong>Unclip in the airlock.</strong> Take the leash off between the two gates. A leashed dog in an off-leash crowd feels trapped, and that tension can start squabbles.</li>
<li><strong>Give the welcome committee a second.</strong> Dogs often rush the gate to greet a newcomer. If the crowd at the gate is big, wait a moment or walk your dog a few steps away from it once inside.</li>
</ul>
<h2>Inside</h2>
<ul>
<li><strong>Eyes up, phone down.</strong> The most important rule. You can't step in early if you aren't watching.</li>
<li><strong>Pick up every time</strong>, even if someone else's dog left it. Bring more bags than you think you need.</li>
<li><strong>Leave food at home.</strong> Treats and snacks can cause scuffles fast. If you train with treats, do it outside the fence.</li>
<li><strong>Think twice about toys.</strong> A favorite ball can turn a sweet dog possessive. Bring a toy you don't mind losing, and pocket it if anyone starts guarding.</li>
<li><strong>Ask before you pet or treat someone else's dog.</strong> Some dogs are nervous, on special diets or in training.</li>
<li><strong>Kids stay close.</strong> Running, squealing kids can trigger chasing. Keep little ones next to you and away from the gate.</li>
</ul>
<h2>Who should sit today out</h2>
<p>Skip the run if your dog is sick, in heat, too young to be fully vaccinated, or just not in the mood. A dog who is grumpy at home is usually grumpy at the run, too.</p>
<h2>Know when to leave</h2>
<p>If your dog is being bullied, bullying, or getting over-excited and can't settle, it's completely fine to leash up and try another day. Nobody at the run will judge you for leaving; they'll respect you for noticing.</p>
<p class="aside-note">Every run posts its own rules by the gate. When they're different from anything here, the posted rules win.</p>
"""),
    dict(slug="first-visit-to-a-dog-run", cat="runs", icon="i-pin", minutes=4, vet=True,
         title="Your dog's first visit to a dog run: a step-by-step plan",
         short="A first visit to a dog run",
         desc="How to make your dog's first trip to a dog run calm and fun: when to go, how to enter, what to watch for and how long to stay.",
         body="""
<p class="lede">A first visit sets the tone for every visit after. The goal isn't a marathon play session; it's a short, happy trip that makes your dog want to come back.</p>
<h2>Before you go</h2>
<ul>
<li><strong>Check the basics.</strong> Make sure vaccinations are current and your dog wears a collar with an ID tag and license. Your vet can tell you when a young dog is ready.</li>
<li><strong>Know a few cues.</strong> A reliable "come" and "leave it" make everything easier. If recall is shaky, practice in a quiet fenced space first.</li>
<li><strong>Burn a little energy.</strong> A 15-minute walk beforehand takes the edge off so your dog arrives curious rather than frantic.</li>
</ul>
<h2>Pick a quiet time</h2>
<p>Weekday mid-mornings and early afternoons tend to be calmer than before-work and after-work rush hours. Use the <a href="/runs">BarksBuds dog run map</a> to find a fenced run close to home, and check whether it has a separate small-dog area if your dog is little.</p>
<h2>Watch from outside first</h2>
<p>Spend a few minutes walking along the fence. Let your dog sniff and look. If the group inside is rowdy, come back another time. There's no prize for going in on a bad day.</p>
<h2>Going in</h2>
<ol>
<li>Step into the double-gate area and close the outer gate.</li>
<li>Unclip the leash before opening the inner gate.</li>
<li>Walk in and keep moving for a minute so your dog isn't swarmed at the gate.</li>
<li>Stay close, stay relaxed and keep your voice upbeat.</li>
</ol>
<h2>Keep it short</h2>
<p>Ten to twenty minutes is plenty for a first visit. Leave while your dog is still having fun, not after they're exhausted or overwhelmed. Call them to you, praise, leash up outside the inner gate, and head home on a high note.</p>
<h2>What to watch for</h2>
<p>Loose, wiggly bodies and dogs taking turns chasing are good signs. Hiding behind your legs, a tucked tail or constant lip-licking mean your dog has had enough. Our guide to <a href="/tips/reading-dog-body-language">reading dog body language</a> covers the details.</p>
"""),
    dict(slug="reading-dog-body-language", cat="runs", icon="i-chat", minutes=5, vet=False,
         title="Reading dog body language: good play, rough play and when to step in",
         short="Reading body language and play",
         desc="Play bows, loose bodies and taking turns versus stiff stances and hard stares: how to tell healthy dog play from trouble at the dog run.",
         body="""
<p class="lede">Dog play can look wild. Growls, open mouths and wrestling are often totally normal. The trick is learning to see the difference between two dogs having a blast and one dog who wants out.</p>
<h2>Signs of healthy play</h2>
<ul>
<li><strong>Loose, bouncy bodies.</strong> Wiggly, curvy movement, not stiff and straight.</li>
<li><strong>Play bows.</strong> Front end down, back end up: "this is all a game."</li>
<li><strong>Taking turns.</strong> The chaser becomes the chased; the dog on the bottom gets to be on top.</li>
<li><strong>Self-handicapping.</strong> A big dog lying down or going gentle so a smaller friend can keep up. Lily, a long-legged poodle mix who runs like a horse, slows right down for smaller dogs like Maggie.</li>
<li><strong>Little breaks.</strong> Good play has pauses: a sniff, a shake-off, a drink of water, then back to it.</li>
</ul>
<h2>Signs a dog is uncomfortable</h2>
<ul>
<li>Tail tucked, ears pinned back, body low</li>
<li>Lip-licking, yawning or turning the head away when another dog approaches</li>
<li>"Whale eye": the whites of the eyes showing</li>
<li>Hiding under a bench or behind their person</li>
<li>Trying to leave, again and again</li>
</ul>
<h2>Signs to step in now</h2>
<ul>
<li>A stiff, frozen body or a hard, fixed stare</li>
<li>One dog repeatedly pinning another who's trying to escape</li>
<li>Several dogs ganging up on one</li>
<li>Play that keeps escalating without any pauses</li>
</ul>
<h2>The "consent test"</h2>
<p>Not sure if both dogs are enjoying it? Gently hold or call away the dog who seems to be "winning." If the other dog bounces right back for more, it's play. If they use the break to leave, they were done, and you just helped them out.</p>
<h2>How to interrupt calmly</h2>
<p>Call your dog in a cheerful voice, walk the other way, or clap and move. Avoid reaching between dogs who are tangled up; if you need to separate two dogs, work with the other owner and guide them apart from behind. Then give everyone a minute to cool off.</p>
<p class="aside-note">Raised hackles on their own don't always mean trouble. They can just mean a dog is excited. Read the whole dog, not one signal.</p>
"""),
    dict(slug="small-vs-large-dog-areas", cat="runs", icon="i-users", minutes=3, vet=False,
         title="Small dog area or large dog area? How to choose",
         short="Small vs large dog areas",
         desc="Many NYC and Long Island dog runs have separate small-dog and large-dog areas. Here's how to choose the right side for your dog.",
         body="""
<p class="lede">Lots of runs across the five boroughs, Long Island and Westchester split into a small-dog area and a large-dog area. The split keeps play fair and safe, and choosing the right side is easier than it looks.</p>
<h2>Why the split matters</h2>
<p>Size differences change everything in play. A friendly 70-pound dog can knock over a 10-pound dog by accident in a single bounce, and fast chases can trigger a big dog's chase instincts toward a tiny, squeaky friend. Separate areas let everyone play at their own speed.</p>
<h2>Follow the sign first</h2>
<p>Many small-dog areas post a weight limit at the gate, often somewhere around 25 to 30 pounds. If a limit is posted, that's the rule. Our <a href="/runs">dog run map</a> shows which runs have a separate small-dog area.</p>
<h2>When it's not posted</h2>
<ul>
<li><strong>Weight is a starting point, not the whole story.</strong> Maggie, our 26-pound merle Frenchie, is right on the line. She's sturdy and confident, but she's built for the couch, not for sprinting with greyhounds.</li>
<li><strong>Match play style, within the rules.</strong> A shy small dog belongs on the small side. A confident small dog who loves running with bigger friends may enjoy the large side, if the run allows it and you watch closely.</li>
<li><strong>Puppies of big breeds</strong> grow fast. Move them to the large-dog area once they outgrow the small-dog limit, even if they still act like babies.</li>
</ul>
<h2>Etiquette on each side</h2>
<ul>
<li>Never bring a large dog into the small-dog area "just for a minute."</li>
<li>If you bring a small dog into the large-dog area, watch closely and leave if the play gets too big.</li>
<li>When in doubt, ask the regulars. They know the crowd at each time of day.</li>
</ul>
"""),
    dict(slug="summer-heat-and-paw-safety", cat="health", icon="i-check", minutes=4, vet=True,
         title="Summer heat and hot pavement: keeping paws and pups safe",
         short="Summer heat and paw safety",
         desc="Hot sidewalks, humid afternoons and flat-faced breeds: practical summer safety for city and suburban dogs, plus the warning signs of overheating.",
         body="""
<p class="lede">New York summers are humid, and city sidewalks soak up the sun all day. A few habits keep summer walks fun and safe.</p>
<h2>The seven-second pavement test</h2>
<p>Press the back of your hand flat on the sidewalk for seven seconds. If it's too hot for your hand, it's too hot for paws. On a sunny afternoon, asphalt can get far hotter than the air, hot enough to burn paw pads.</p>
<ul>
<li>Walk early in the morning and in the evening.</li>
<li>Stick to grass and shady sides of the street.</li>
<li>Choose runs with shade and water. Our <a href="/runs">dog run map</a> flags water where we know it.</li>
<li>Booties can help on unavoidable hot stretches, if your dog has practiced wearing them.</li>
</ul>
<h2>Know your dog's risk</h2>
<p>Flat-faced breeds like French bulldogs (hello, Maggie), pugs and boxers have a harder time cooling off. So do seniors, puppies, heavy-coated dogs and dogs carrying extra weight. On hot days, keep their outings short and gentle.</p>
<h2>Cooling tips</h2>
<ul>
<li>Bring water and a collapsible bowl, and offer drinks often.</li>
<li>Take shade breaks before your dog asks for them.</li>
<li>Never leave a dog in a parked car, even for a quick errand. Cars heat up fast, even with the windows cracked.</li>
<li>Skip the long run or fetch session when it's hot and humid; save it for a cool morning.</li>
</ul>
<h2>Warning signs of overheating</h2>
<p>Heavy, frantic panting, thick drool, bright red or pale gums, stumbling, vomiting, or a dog who suddenly lies down and won't get up. If you see these, move into shade or air conditioning, offer small sips of water, wet your dog with cool (not ice-cold) water, and <strong>call your vet or an emergency vet right away</strong>. Overheating can become serious quickly.</p>
"""),
    dict(slug="winter-salt-and-cold", cat="health", icon="i-check", minutes=4, vet=True,
         title="Winter walks: road salt, ice and cold-weather care",
         short="Winter salt and cold",
         desc="Rock salt, ice melt, slushy curbs and short winter days: how to protect paws and keep dogs comfortable through a New York winter.",
         body="""
<p class="lede">Snow days can be a dog's favorite days. The tricky part is everything that comes with them: salted sidewalks, icy curbs, slush puddles and early sunsets.</p>
<h2>Salt and ice melt</h2>
<p>Rock salt and many ice melts can dry out and irritate paw pads, and dogs may lick them off their feet later.</p>
<ul>
<li><strong>Wipe paws after every walk</strong> with a damp cloth or a quick rinse, including between the toes.</li>
<li><strong>Use a pet-friendly ice melt</strong> on your own steps and driveway.</li>
<li><strong>Try paw balm</strong> before walks, or booties if your dog will wear them.</li>
<li><strong>Trim the fur between toes</strong> on fluffy-footed dogs so ice balls don't build up.</li>
</ul>
<h2>Keep an eye out for</h2>
<ul>
<li><strong>Antifreeze.</strong> Puddles in driveways and parking lots can contain it, and even a small amount is very dangerous to dogs. Steer clear of mystery puddles and call your vet immediately if you think your dog licked some.</li>
<li><strong>Thin ice.</strong> Keep dogs off frozen ponds, lakes and the edges of the Sound.</li>
<li><strong>Limping or licking</strong> paws after a walk, which can mean irritation or a small cut.</li>
</ul>
<h2>Staying warm</h2>
<p>Small dogs, short-coated dogs, seniors and puppies get cold faster. A coat or sweater can help, and shorter, more frequent walks beat one long, frigid one. If your dog is shivering, lifting paws or trying to turn for home, listen to them.</p>
<h2>Shorter days</h2>
<p>With early sunsets, a light-up collar or reflective leash makes you both easier to see. Many town parks close at dusk, so check hours before an evening trip to the run.</p>
"""),
    dict(slug="ticks-and-lyme-on-long-island", cat="health", icon="i-check", minutes=5, vet=True,
         title="Ticks and Lyme disease on Long Island: a dog owner's guide",
         short="Ticks and Lyme on Long Island",
         desc="Ticks are common on Long Island and in Westchester. How to do a quick tick check, remove a tick safely and talk with your vet about prevention.",
         body="""
<p class="lede">Long Island, Westchester and the wooded edges of the city are prime tick country. Ticks can carry Lyme disease and other illnesses, so a quick check after walks is one of the best habits a dog owner can have.</p>
<h2>Where and when</h2>
<p>Ticks like tall grass, leaf litter, brush and the edges of woods and beaches. They're most active from spring through fall, but adult ticks can be out on any mild winter day, too. Several kinds live in our area, including blacklegged (deer) ticks, which can spread Lyme disease, and lone star ticks, which are common on Long Island.</p>
<h2>The two-minute tick check</h2>
<p>After walks in grassy or wooded areas, run your fingers slowly through your dog's coat, feeling for small bumps. Pay extra attention to:</p>
<ul>
<li>In and around the ears</li>
<li>Around the eyes and on the head</li>
<li>Under the collar</li>
<li>Armpits and the groin</li>
<li>Between the toes</li>
<li>Around the tail</li>
</ul>
<p>Curly and dark coats make ticks harder to spot. Lily's black and grey curls hide them well, so a fine-toothed comb helps. Check yourself, too.</p>
<h2>Removing a tick</h2>
<ol>
<li>Use fine-tipped tweezers or a tick-removal tool.</li>
<li>Grasp the tick as close to the skin as you can.</li>
<li>Pull straight out with slow, steady pressure. Don't twist, squeeze or burn it.</li>
<li>Clean the spot and wash your hands.</li>
<li>Note the date. Some owners save the tick in a sealed bag in case the vet wants to see it.</li>
</ol>
<h2>Prevention</h2>
<p>There are many tick prevention options for dogs, and a Lyme vaccine is available too. The right choice depends on your dog's health, age and lifestyle, so this is a great conversation to have with your vet.</p>
<h2>When to call the vet</h2>
<p>Lyme and other tick-borne illnesses can show up weeks after a bite. Call your vet if your dog has a fever, seems tired, loses appetite, has swollen joints, or starts limping, especially if the limp moves from leg to leg.</p>
"""),
    dict(slug="vaccines-and-licenses-for-dog-runs", cat="health", icon="i-check", minutes=4, vet=True,
         title="Vaccines and licenses: what dog runs usually expect",
         short="Vaccines and licensing",
         desc="Most NYC, Long Island and Westchester dog runs expect current vaccinations and a dog license. A general guide, and who to ask for the exact rules.",
         body="""
<p class="lede">Before your first visit to a dog run, it's worth making sure the paperwork is in order. Rules vary by city, town and park, so think of this as a general guide and a checklist of who to ask.</p>
<h2>What most runs expect</h2>
<ul>
<li><strong>A current rabies vaccination.</strong> Rabies vaccination is required for dogs in New York, and runs commonly expect it.</li>
<li><strong>A dog license</strong> from the city, town or village where you live, with the tag on your dog's collar.</li>
<li><strong>Other core vaccines</strong>, such as distemper and parvovirus, which your vet will usually recommend for any dog that meets other dogs.</li>
<li><strong>Healthy dogs only.</strong> Many runs ask you to keep sick dogs and dogs in heat at home, and some set a minimum age for puppies.</li>
</ul>
<h2>Vaccines to ask your vet about</h2>
<p>Depending on your dog's lifestyle, your vet may also suggest vaccines for things like kennel cough (Bordetella), leptospirosis, canine influenza or Lyme disease. Dogs who visit runs, daycare or groomers often meet a lot of other dogs, so mention that at your next checkup.</p>
<h2>Licensing</h2>
<p>In New York, dog licenses are handled locally. In the five boroughs that's the city; on Long Island and in Westchester it's usually your town, city or village clerk. Many places let you apply online, and the license tag helps get a lost dog home faster.</p>
<h2>Town and resident rules</h2>
<p>Some dog parks run by towns or counties are open only to residents, or ask for a park pass or permit. Check the park's page or the sign at the gate before you go. Our <a href="/runs">dog run map</a> links to official sources where we have them.</p>
<h2>Keep proof handy</h2>
<p>Snap a photo of your dog's vaccination record and license and keep it on your phone. On BarksBuds, you can also add a "vaccinations up to date" badge to your dog's profile. It's self-reported, so it's a friendly signal rather than a guarantee.</p>
<p class="aside-note">Rules change, and every town is a little different. For the exact requirements where you live, check with your city or town clerk, the park that runs the dog run, and your vet.</p>
"""),
    dict(slug="hosting-a-great-meetup", cat="community", icon="i-cal", minutes=4, vet=False,
         title="How to host a great dog meetup",
         short="Hosting a good meetup",
         desc="Pick the right run, the right time and the right size: a simple playbook for hosting a friendly dog meetup on BarksBuds.",
         body="""
<p class="lede">The best meetups feel easy: a good spot, a friendly host, a group that's the right size. Here's a simple playbook for hosting one on BarksBuds.</p>
<h2>Pick the place</h2>
<ul>
<li>Choose a fenced run with room for a group. Use the <a href="/runs">dog run map</a> to check for water, shade and a small-dog area.</li>
<li>Name a clear meeting spot, like "by the double gate" or "the benches near the water fountain."</li>
<li>Think about parking or transit so people can actually get there.</li>
</ul>
<h2>Pick the time</h2>
<ul>
<li>Weekend mornings are popular. Weekday evenings work well in spring and summer.</li>
<li>Avoid the run's busiest hour so your group isn't squeezed in.</li>
<li>Keep it to about an hour. Dogs get tired, and leaving on a high note brings people back.</li>
</ul>
<h2>Set the vibe</h2>
<ul>
<li><strong>Say who it's for.</strong> "Small dogs," "puppies under a year," "high-energy fetch fans" or "everyone welcome" all help the right people find you.</li>
<li><strong>Set a cap.</strong> Ten to fifteen dogs is plenty for most runs. BarksBuds keeps a waitlist if you fill up.</li>
<li><strong>Mention the basics.</strong> Current vaccinations, no dogs in heat, bring water and bags.</li>
</ul>
<h2>On the day</h2>
<ul>
<li>Arrive ten minutes early and say hi to everyone at the gate.</li>
<li>Introduce people by their dogs' names. Everyone remembers the dogs first.</li>
<li>Keep an eye on the play and be the one who calls a quick break if things get rowdy.</li>
<li>Check the weather. If it's pouring or dangerously hot, update the meetup early so nobody makes a wasted trip.</li>
</ul>
<h2>Afterward</h2>
<p>Post a thank-you and a photo, and set the next date while everyone's still smiling. That's how one meetup becomes a regular thing, and a regular thing becomes a <a href="/tips/starting-a-pack">pack</a>.</p>
<p><a class="btn btn-sm" href="/meetups/new">Host a meetup</a></p>
"""),
    dict(slug="starting-a-pack", cat="community", icon="i-users", minutes=4, vet=False,
         title="Starting a pack: how to build a friendly local dog group",
         short="Starting a pack",
         desc="A pack is a standing group of local dog owners. How to start one on BarksBuds, set a friendly tone and keep people coming back.",
         body="""
<p class="lede">A pack is a standing group: the neighbors you see every Saturday at the run, the small-dog crew, the early-morning walkers. Here's how to start one that lasts.</p>
<h2>Give it a clear focus</h2>
<p>The best packs are easy to describe in one line. A few ideas:</p>
<ul>
<li><strong>A place:</strong> "Manhasset and North Shore dogs"</li>
<li><strong>A time:</strong> "Sunrise walkers in Riverside Park"</li>
<li><strong>A kind of dog:</strong> "Frenchies and friends" or "Big, bouncy dogs of Westchester"</li>
<li><strong>A stage of life:</strong> "Puppies' first year" or "Seniors who like a slow stroll"</li>
</ul>
<h2>Write a warm description</h2>
<p>Say who it's for, where you usually meet and how often. Add a photo of your own dog. People join people, and a friendly face helps.</p>
<h2>Set simple house rules</h2>
<ul>
<li>Be kind, and keep the board about dogs.</li>
<li>Current vaccinations, and dogs who enjoy other dogs.</li>
<li>Follow each run's posted rules.</li>
</ul>
<p>Short and friendly beats long and strict.</p>
<h2>Keep a rhythm</h2>
<p>A regular schedule, like "every Saturday at 9," does more than any amount of posting. Put the next few meetups on the calendar so new members always have something to say yes to.</p>
<h2>Share the leash</h2>
<p>Invite one or two regulars to help organize. Co-organizers can approve join requests, host when you're away and bring their own ideas.</p>
<h2>Welcome newcomers</h2>
<p>Greet new members by their dog's name, introduce them at their first meetup, and check in after. A pack grows one good first impression at a time.</p>
<p><a class="btn btn-sm" href="/packs">Find or start a pack</a></p>
"""),
    dict(slug="puppy-socialization", cat="puppies", icon="i-paw", minutes=5, vet=True,
         title="Puppy socialization: building a confident, friendly dog",
         short="Puppy socialization",
         desc="Early, gentle, positive experiences help puppies grow into confident dogs. A practical guide to safe puppy socialization before and after vaccines.",
         body="""
<p class="lede">Puppies are especially open to new experiences in their first few months. Gentle, positive introductions to the world during that time can help them grow into relaxed, confident adult dogs.</p>
<h2>Quality over quantity</h2>
<p>Socialization isn't about meeting as many dogs as possible. It's about lots of small, happy experiences: new sounds, surfaces, people and places, each paired with treats and calm praise. If your puppy seems scared, back off and try again from farther away.</p>
<h2>Before vaccinations are complete</h2>
<p>Your vet will tell you when your puppy is ready for dog runs and other busy dog spaces. Until then, there's still plenty to do:</p>
<ul>
<li>Carry your puppy around the neighborhood to watch buses, bikes and people.</li>
<li>Invite friends over, including kids who can be calm and gentle.</li>
<li>Arrange playdates with healthy, vaccinated, puppy-friendly adult dogs you know.</li>
<li>Ask your vet about puppy classes, which are usually run with health requirements in place.</li>
</ul>
<h2>A socialization checklist</h2>
<ul>
<li><strong>People:</strong> hats, beards, umbrellas, strollers, wheelchairs, kids</li>
<li><strong>Sounds:</strong> sirens, trucks, the vacuum, the doorbell, thunder (try recordings at a low volume first)</li>
<li><strong>Surfaces:</strong> grass, gravel, metal grates, stairs, elevators, wet sidewalks</li>
<li><strong>Handling:</strong> touching paws and ears, brushing, nail trims, car rides</li>
<li><strong>Alone time:</strong> short, calm stretches by themselves</li>
</ul>
<h2>Your puppy's first dog run</h2>
<p>When your vet gives the green light, start with a quiet time and a small group. Many runs have a separate small-dog area, which can be gentler for little puppies. Keep the visit short, watch closely, and step in if bigger dogs get too rough. See our guide to a <a href="/tips/first-visit-to-a-dog-run">first visit to a dog run</a>.</p>
<h2>Signs to slow down</h2>
<p>Hiding, freezing, a tucked tail, or refusing treats all mean "too much." Take a break and make the next step easier. If your puppy seems fearful often, ask your vet or a certified trainer for help early; it's much easier to work on when they're young.</p>
"""),
    dict(slug="dog-run-checklist", cat="runs", icon="i-check", minutes=2, vet=False,
         title="What to bring to the dog run: a simple checklist",
         short="What-to-bring checklist",
         desc="Leash, bags, water and more: a quick checklist for every trip to the dog run, with seasonal extras for summer heat and winter salt.",
         body="""
<p class="lede">Keep a small bag packed by the door and you'll never be the person borrowing poop bags at the gate.</p>
<h2>Every trip</h2>
<ul class="checklist">
<li>Leash (a regular leash is easier to handle at the gate than a retractable one)</li>
<li>Collar or harness with an ID tag and license tag</li>
<li>Poop bags, plus a few spares to share</li>
<li>Water and a collapsible bowl</li>
<li>Treats in a closed pocket, for training outside the fence</li>
<li>A small towel for muddy paws and wet dogs</li>
<li>Your phone, with your vet's number saved</li>
<li>A photo of your dog's vaccination record</li>
</ul>
<h2>Nice to have</h2>
<ul class="checklist">
<li>A toy you don't mind losing</li>
<li>A tick comb or lint roller for after grassy walks</li>
<li>Hand wipes or sanitizer</li>
<li>A basic pet first-aid kit in the car</li>
</ul>
<h2>Summer extras</h2>
<ul class="checklist">
<li>Extra water</li>
<li>A cooling bandana or vest for warm days</li>
<li>Booties for hot pavement</li>
</ul>
<h2>Winter extras</h2>
<ul class="checklist">
<li>Paw balm or booties</li>
<li>A coat for small or short-coated dogs</li>
<li>Wipes for salty paws</li>
<li>A light-up collar for early sunsets</li>
</ul>
<p>Ready? <a href="/runs">Find a dog run near you</a>.</p>
"""),
]

for _t in TIPS:
    _t.setdefault("updated", UPDATED)

BY_SLUG = {t["slug"]: t for t in TIPS}
