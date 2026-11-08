# ⚡ Patrouille Éclair — jeu interactif pour TikTok LIVE

Jeu original (personnages et décor inventés) : les Gluobots du Dr. Boulon attaquent Ville-Étincelle et le public du live défend la ville.

## Ce que fait chaque action
| Action sur le live | Dans le jeu |
|---|---|
| 💬 Commentaire | Tire un éclair avec le pseudo de la personne |
| ❤️ J'aime | Remplit la barre d'énergie → ONDE qui touche tous les ennemis |
| ➕ Abonnement | La personne devient un héros permanent de la Patrouille (il tire tout seul) |
| 🔁 Partage | Répare 4 % de la ville |
| 🌹 Cadeau 1+ pièce | ÉCLAIR : 3 éclairs guidés |
| 🎁 2+ pièces | MISSILE avec explosion |
| 💎 10+ pièces | GÉANT : héros géant au nom du donateur pendant 15 s |
| 👑 100+ pièces | BOUCLIER de 20 s + réparation |
| 🦁 500+ pièces | TEMPÊTE : nettoie l'écran et énormes dégâts au boss |

Toutes les 5 vagues, le boss Dr. Boulon arrive. Si la ville tombe, elle se reconstruit en 8 s et le classement continue.
Les combos de cadeaux (ex. 10 roses d'affilée) comptent chaque unité une seule fois. Le classement met aussi en avant
ceux qui commentent et aiment, pas seulement les donateurs.

## Mettre le jeu sur le live (PC)
1. **Installez TikFinity** sur le PC (logiciel gratuit qui lit les événements de votre live) et connectez votre compte TikTok.
   TikTok n'a pas d'API officielle pour les événements LIVE ; TikFinity est un outil tiers très utilisé.
2. **Ouvrez** `patrouille-eclair.html` dans le navigateur du PC. Dans le panneau, choisissez « TikFinity » puis **Connecter**.
   - Adresse par défaut : `ws://localhost:21213/`. Si ça ne se connecte pas, vérifiez dans les réglages de TikFinity
     l'option API / WebSocket et collez l'adresse indiquée.
3. **Testez sans live** avec les boutons du panneau ou « Simulation automatique ».
4. **Pendant la diffusion** :
   - **OBS** : Source → *Navigateur* → cochez *Fichier local* → choisissez le fichier HTML. Taille **1080 × 1920**.
     Pour se connecter automatiquement : ajoutez `?ws=ws://localhost:21213/` à la fin de l'adresse.
   - **TikTok LIVE Studio** : ajoutez le jeu comme source lien/navigateur (si votre version le propose) ou capturez la fenêtre du navigateur.
   - Option : `&transparent=1` rend le fond transparent pour le superposer à votre caméra.
5. Touche **P** : afficher/masquer le panneau de contrôle (masquez-le avant de commencer).

## Règles TikTok pour les cadeaux
- En général, il faut **18 ans et au moins 1 000 abonnés** pour recevoir des cadeaux ; envoyer des cadeaux est aussi réservé aux majeurs.
- Le jeu est fait pour que tout le monde participe gratuitement (commenter, aimer, s'abonner, partager). Évitez de pousser
  le public à envoyer des cadeaux, surtout avec un public jeune — cela protège aussi votre compte.
- N'utilisez pas les noms, logos, images ou musiques de la série Henry Danger pendant le live (droits de Nickelodeon).
