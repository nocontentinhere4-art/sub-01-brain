# Rig con mixamo.com — solo come ripiego

Serve solo se il rig automatico (`room_build/rig/autorig.sh`, senza mixamo.com) non viene accettato.

1. Prepara lo ZIP (da `room_build/`):
   `rig/mixamo_upload.sh ../web/room/char_v5.glb /tmp/personaggio.zip`
   (circa 160 mila triangoli, texture 2048² JPEG, circa 4–5 MB).
2. Apri mixamo.com e accedi con il tuo account Adobe.
3. Clicca **Upload Character** e trascina lo ZIP.
4. Se chiede l'orientamento: il personaggio guarda verso di te (+Z), in piedi. Conferma con **Next**.
5. Metti i marcatori: mento, polsi, gomiti, ginocchia, inguine.
6. **Skeleton LOD**: scegli **Standard Skeleton (65)**, con le dita. Clicca **Next**.
7. Controlla l'anteprima che si muove: mani, spalle e fianchi devono piegarsi bene. Clicca **Next**.
8. Clicca **Download**:
   - Format: **FBX Binary (.fbx)**
   - Skin: **With Skin**
   - Pose: **T-pose**, nessuna animazione
9. Passa il file FBX al team (non metterlo nel repository).
10. Il team lo importa (da `room_build/`):
    `rig/mixamo_import.sh personaggio.fbx ../web/room/char_mixamo.glb ../web/room/char_v5.glb`
    poi lancia i controlli: `kimodo/rig_change.mjs`.
