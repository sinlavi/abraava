t_name = track.get("trackName", "Unknown Title")
ye = track.get("releaseDate", "").split("-")[0]
a_name = track.get("artistName", "Unknown Artist")
collection_name = track.get("collectionName", "")
cover_url = get_high_res_artwork(track.get("artworkUrl100", track.get("artworkUrl")), size=600)

query = f'"{t_name}" by {a_name} collection {collection_name} {ye}'

try:
    video_id = await search_youtube_track(query)
    if not video_id:
        await send_error_with_retry(bot, chat_id, f"نتوانستیم لینک یوتیوب موزیک را برای این آهنگ پیدا کنیم.",
                                    f"download_retry:{track_id}", status_msg)
        return
    video_url = f"https://music.youtube.com/watch?v={video_id}"

    await update_status_with_close(status_msg, f"⏳ *در صف دانلود و آماده‌سازی...*{FOOTER}")

    mp3_path_str = None
    try:
        async with DOWNLOAD_SEMAPHORE:
            await update_status_with_close(status_msg,
                                           f"⏳ *در حال دانلود و پردازش (روش‌های پیشرفته ضدتحریم)...*{FOOTER}")
            mp3_path_str = await asyncio.get_event_loop().run_in_executor(
                None, download_audio, video_url
            )

            if not mp3_path_str:
                await send_error_with_retry(bot, chat_id, f"دانلود با شکست مواجه شد — همه ۸ روش ناموفق بودند.",
                                            f"download_retry:{track_id}", status_msg)
                return

            file_size_mb = await asyncio.to_thread(_get_file_size_sync, mp3_path_str)
            if file_size_mb == 0:
                await send_error_with_retry(bot, chat_id, f"خطای داخلی: فایل دانلود شده یافت نشد.",
                                            f"download_retry:{track_id}", status_msg)
                return

            cover_bytes = None
            if cover_url and HTTP_SESSION:
                try:
                    async with HTTP_SESSION.get(cover_url) as resp:
                        if resp.status == 200:
                            cover_bytes = await resp.read()
                except Exception as e:
                    logger.error(f"Failed to download cover: {e}")

            await asyncio.get_event_loop().run_in_executor(
                None, tag_mp3, mp3_path_str, track, cover_bytes
            )
            await update_status_with_close(status_msg,
                                           f"☁️ *در حال آپلود در سرورهای ابری {BOT_NAME}...*{FOOTER}")
            await send_audio_with_retry(
                bot, chat_id, mp3_path_str, f"{t_name}.mp3", caption, cache_id=str(track['trackId'])
            )

            await status_msg.delete()

    except Exception as e:
        logger.exception("Download error")
        await send_error_with_retry(bot, chat_id, f"خطا در عملیات: {str(e)[:100]}",
                                    f"download_retry:{track_id}", status_msg)
    finally:
        if mp3_path_str:
            await asyncio.to_thread(_delete_file_sync, mp3_path_str)

except Exception as e:
    await send_error_with_retry(bot, chat_id, f"خطا در جستجوی یوتیوب: {str(e)[:100]}",
                                f"download_retry:{track_id}", status_msg)

msg = await bot.send_voice(chat_id, voice=preview_url,
                           caption=f"🎧 *پیش‌نمایش صوتی آهنگ {track.get('trackName')}*{FOOTER}")

msg = await bot.send_photo(chat_id, photo=artwork_url, caption=text, reply_markup=markup)
if cache_id and not artwork_cache and msg:
    await set_mirror('collection', cache_id, 'artworkUrl',
                     'https://tapi.bale.ai/file/bot<token>/' + str(msg.photo[0].id))
