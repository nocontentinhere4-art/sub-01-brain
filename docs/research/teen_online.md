# What people aged about 16–20 do online (#89, owner request 2026-10-04)

Owner: "Why is he looking at recipes… he's a young guy like us. Have him watch YouTube and TikTok, look up really
interesting things, cars maybe. Look up what young people do online and have him do the same."

SUB-01 is a fictional man of about 20 in Tokyo, never presented as a minor. The studies below are mostly about teens
(13–17) and Gen Z (up to the mid-20s); they set the mix of his platforms and interests, not his age.

## Platforms

- **YouTube is the default.** 9 in 10 US teens use it and about 73 % use it every day. TikTok and Instagram are used
  by about 6 in 10, Snapchat by 55 %. About 60 % use TikTok daily and 16 % say they are on it "almost constantly".
  (Pew Research Center, *Teens, Social Media and Technology 2024*, survey of 1,391 US teens, Sept–Oct 2024:
  https://www.pewresearch.org/internet/2024/12/12/teens-social-media-and-technology-2024/)
- **Video is most of it, and short video is growing.** In the UK, 96 % of 3–17-year-olds watch videos on
  video-sharing sites and apps, and 80 % of 16–17-year-olds watch live-streamed video. YouTube is used by 88 %;
  TikTok rose from 50 % to 53 % and Snapchat from 42 % to 46 % in a year. (Ofcom, *Children and Parents: Media Use and
  Attitudes Report 2025*, 7 May 2025:
  https://www.ofcom.org.uk/media-use-and-attitudes/media-habits-children/children-and-parents-media-use-and-attitudes-report-2025)
- **Time:** teens average more than 8.5 hours a day on screens for entertainment. That includes about 1 h 22 min of
  online video, the fastest-growing part of it, and 1 h 46 min of gaming. 77 % watch online videos every day.
  (Common Sense Media, *The Common Sense Census: Media Use by Tweens and Teens, 2021*:
  https://www.commonsensemedia.org/about-us/news/press-releases/the-common-sense-census-media-use-by-tweens-and-teens-new-research)

## Topics

- **Music:** 74 % of US teens watch music videos and 79 % listen to music on YouTube. (Precise TV and Giraffe
  Insights, *PARTY USA Summer 2024*, 1,000 US teens:
  https://www.netinfluencer.com/party-usa-summer-2024-study/)
- **Gaming, played and watched:** 74 % regularly watch other people play video games (MrBeast Gaming and Minecraft
  channels among the favourites). Gaming is also the second-largest block of teen screen time in Common Sense's census.
  (PARTY USA 2024, ibid.; Common Sense 2021, ibid.)
- **Creators and YouTubers:** MrBeast, Dude Perfect and similar creator channels lead teens' favourite channels.
  (PARTY USA 2024, ibid.)
- **Sport:** 41 % of Gen Z name sports as a top interest. In the US, 65 % of 13–24-year-olds call themselves NFL fans;
  in Japan and Europe the equivalent is football (soccer). (admeira, *Consumer Insights Gen Z 2024*:
  https://admeira.ch/fileadmin/admeira.ch/03-Studien/Downloadcenter_FJP_24/Consumer_Insights_Gen_Z_2024_EN.pdf;
  YPulse, 2025: https://www.ypulse.com/newsfeed/2025/05/27/is-gen-z-watching-more-anime-than-football/)
- **Anime:** among Gen Z, anime viewing rivals following a sports league. (YPulse 2025, ibid.)
- **Movies, series and music together:** a top interest for 42 % of Gen Z. (admeira 2024, ibid.)
- **Sneakers and streetwear:** 89 % of Gen Z bought at least one pair of sneakers in the last year, and streetwear
  brands lead their fashion. (MakerSights, *Gen Z Footwear Study*: https://www.makersights.com/resources/gen-z-footwear-study)
- **Cars:** a smaller but real interest, at 21 % of Gen Z. For a young man in Tokyo this means JDM cars, drifting,
  F1 and car channels. (admeira 2024, ibid.)
- **Tech and phones, memes, internet culture:** a constant across these surveys, and the core of short-video feeds.

## What this changes in SUB-01

- **Interest profile** (`interests.PROFILE`), heaviest first: games, cars, anime, music, creators, football, tech,
  sneakers, memes, movies; then Tokyo and science; Wikipedia barely. Food has weight 0 unless he is hungry or ordering
  (`pick(hungry=True)`). There are no money or crypto topics.
- **Where the time goes:** the phone is always the short-video feed. About half of desk time is YouTube, in 20-minute
  sessions (`search_sources.desk_video`), more in the evening. Video plays in YouTube's official embed player and is
  found only through YouTube's official Data API (`YOUTUBE_API_KEY`): the latest uploads of well-known channels per
  topic (channels.list → playlistItems.list → videos.list, 3 units) or a search (100 units). YouTube's Terms of
  Service forbid automated access to its pages, so its pages and RSS are never read. Without a key or quota nothing
  new is looked up, and the panel says so. TikTok plays in its official player.
- **Searches land on sites that fit:** MyAnimeList for anime, Carscoops for cars, PC Gamer for games, TMDB for movies,
  NME for music, 9to5Mac / Hacker News for tech. Each robots.txt allows its search path (checked 2026-10-04).
  General engines (DuckDuckGo, Bing, Brave, Mojeek, Startpage, Qwant, Ecosia) all disallow their results pages, or
  challenge datacenter IPs.
- **Not used:** YouTube's own pages and RSS (its Terms of Service forbid automated access; robots.txt also
  disallows `/feeds/videos.xml`), old.reddit.com (robots.txt disallows all paths), and TikTok's `/embed/v2` and
  `/search` (disallowed). TikTok's tag and discover pages render no video on the server.
