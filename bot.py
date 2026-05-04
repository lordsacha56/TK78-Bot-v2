import json
import os
from pathlib import Path
 
import discord
from discord import app_commands
from discord.ext import commands
 
# =====================  CONFIGURATION  =====================
BOT_TOKEN = os.getenv("DISCORD_TOKEN")
 
# IDs des salons (clic droit sur le salon -> "Copier l'ID" en mode développeur)
CANDIDATURE_CHANNEL_ID = 1476724850448928788   # salon où le bouton est posté
LISTE_CHANNEL_ID = 1476732228171075817         # salon où la liste apparaît
 
# Fichier local pour persister les candidatures et l'ID du message liste
DATA_FILE = Path(__file__).parent / "candidats.json"
# ===========================================================
 
 
# ----------- Persistance simple en JSON -------------
def charger_donnees() -> dict:
    if DATA_FILE.exists():
        try:
            return json.loads(DATA_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return {"message_id": None, "candidats": []}
 
 
def sauvegarder_donnees(data: dict) -> None:
    DATA_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                         encoding="utf-8")
 
 
# ----------- Bot -------------
intents = discord.Intents.default()
intents.message_content = True  # nécessaire pour la commande !setup
bot = commands.Bot(command_prefix="!", intents=intents)
 
 
# ----------- Modal (formulaire) -------------
class CandidatureModal(discord.ui.Modal, title="Candidature - Vidéo du mois"):
    pseudo = discord.ui.TextInput(
        label="Ton pseudo",
        placeholder="Ex : MonPseudo",
        required=True,
        max_length=80,
    )
    titre = discord.ui.TextInput(
        label="Titre de ta vidéo sélectionnée",
        placeholder="Ex : Mon super montage de mai",
        required=True,
        max_length=200,
        style=discord.TextStyle.short,
    )
 
    async def on_submit(self, interaction: discord.Interaction):
        # On répond TOUT DE SUITE pour éviter le timeout de 3s.
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            data = charger_donnees()
 
            # On enregistre la candidature : un utilisateur ne peut être
            # qu'une seule fois dans la liste (sa dernière candidature gagne).
            candidats = [c for c in data["candidats"]
                         if c["user_id"] != interaction.user.id]
            candidats.append({
                "user_id": interaction.user.id,
                "pseudo": str(self.pseudo.value).strip(),
                "titre": str(self.titre.value).strip(),
            })
            data["candidats"] = candidats
 
            # Mise à jour (ou création) du message liste dans l'autre salon
            await mettre_a_jour_liste(data)
 
            sauvegarder_donnees(data)
 
            await interaction.followup.send(
                "✅ Ta candidature a bien été enregistrée !",
                ephemeral=True,
            )
        except Exception as e:
            # Log côté console + message clair côté utilisateur
            import traceback
            traceback.print_exc()
            await interaction.followup.send(
                f"❌ Erreur lors de l'enregistrement : `{type(e).__name__}: {e}`\n"
                "Vérifie que `LISTE_CHANNEL_ID` est correct et que le bot a "
                "les permissions **Voir le salon**, **Envoyer des messages** "
                "et **Lire l'historique** dans ce salon.",
                ephemeral=True,
            )
 
    async def on_error(self, interaction: discord.Interaction, error: Exception):
        import traceback
        traceback.print_exception(type(error), error, error.__traceback__)
        if interaction.response.is_done():
            await interaction.followup.send(
                f"❌ Erreur : `{type(error).__name__}: {error}`",
                ephemeral=True,
            )
        else:
            await interaction.response.send_message(
                f"❌ Erreur : `{type(error).__name__}: {error}`",
                ephemeral=True,
            )
 
 
# ----------- View persistante avec le bouton -------------
class CandidatureView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)  # vue persistante (survit aux redémarrages)
 
    @discord.ui.button(
        label="Candidater",
        style=discord.ButtonStyle.primary,
        emoji="🎬",
        custom_id="candidature_video_du_mois",  # custom_id => vue persistante
    )
    async def candidater(self, interaction: discord.Interaction,
                         button: discord.ui.Button):
        await interaction.response.send_modal(CandidatureModal())
 
 
# ----------- Construction et envoi du message liste -------------
def construire_contenu_liste(data: dict) -> str:
    lignes = ["**Liste des membres candidats ainsi que le titre de leur vidéo sélectionnée :**", ""]
    if not data["candidats"]:
        lignes.append("_Aucune candidature pour le moment._")
    else:
        for c in data["candidats"]:
            # @pseudo (saisi dans le formulaire) / Titre vidéo
            lignes.append(f"- @{c['pseudo']} / {c['titre']}")
    return "\n".join(lignes)
 
 
async def mettre_a_jour_liste(data: dict) -> None:
    salon = bot.get_channel(LISTE_CHANNEL_ID)
    if salon is None:
        try:
            salon = await bot.fetch_channel(LISTE_CHANNEL_ID)
        except discord.NotFound:
            raise RuntimeError(
                f"Salon LISTE_CHANNEL_ID={LISTE_CHANNEL_ID} introuvable. "
                "Vérifie l'ID."
            )
        except discord.Forbidden:
            raise RuntimeError(
                f"Le bot n'a pas accès au salon {LISTE_CHANNEL_ID}. "
                "Ajoute-le et donne-lui les permissions nécessaires."
            )
 
    contenu = construire_contenu_liste(data)
    message_id = data.get("message_id")
 
    if message_id:
        try:
            msg = await salon.fetch_message(message_id)
            await msg.edit(content=contenu,
                           allowed_mentions=discord.AllowedMentions.none())
            return
        except (discord.NotFound, discord.Forbidden):
            pass  # on recrée un message ci-dessous
 
    msg = await salon.send(contenu,
                           allowed_mentions=discord.AllowedMentions.none())
    data["message_id"] = msg.id
 
 
# ----------- Événements -------------
@bot.event
async def on_ready():
    # On enregistre la vue persistante pour que le bouton fonctionne après
    # un redémarrage du bot.
    bot.add_view(CandidatureView())
    try:
        await bot.tree.sync()
    except Exception:
        pass
    print(f"Connecté en tant que {bot.user} (id={bot.user.id})")
 
 
# ----------- Commande pour publier le message avec le bouton -------------
@bot.command(name="setup")
@commands.has_permissions(manage_guild=True)
async def setup_message(ctx: commands.Context):
    """Publie le message avec le bouton dans le salon de candidature."""
    if ctx.channel.id != CANDIDATURE_CHANNEL_ID:
        await ctx.reply(
            "Cette commande doit être utilisée dans le salon de candidature configuré.",
            mention_author=False,
        )
        return
 
    contenu = (
        "Pour candidater afin qu'une de tes vidéos devienne la vidéo du mois, "
        "clique sur le bouton ci-dessous.\n👇👇👇"
    )
    await ctx.send(contenu, view=CandidatureView())
    try:
        await ctx.message.delete()
    except discord.Forbidden:
        pass
 
 
# Variante slash : /setup
@bot.tree.command(name="setup", description="Publier le message de candidature avec le bouton")
@app_commands.default_permissions(manage_guild=True)
async def slash_setup(interaction: discord.Interaction):
    if interaction.channel_id != CANDIDATURE_CHANNEL_ID:
        await interaction.response.send_message(
            "Cette commande doit être utilisée dans le salon de candidature configuré.",
            ephemeral=True,
        )
        return
    contenu = (
        "Pour candidater afin qu'une de tes vidéos devienne la vidéo du mois, "
        "clique sur le bouton ci-dessous.\n👇👇👇"
    )
    await interaction.channel.send(contenu, view=CandidatureView())
    await interaction.response.send_message("Message publié ✅", ephemeral=True)
 
 
# ----------- Lancement -------------
if __name__ == "__main__":
    if BOT_TOKEN == "METS_TON_TOKEN_ICI":
        raise SystemExit(
            "Configure ton token : variable d'environnement DISCORD_TOKEN "
            "ou la constante BOT_TOKEN en haut du fichier."
        )
    bot.run(BOT_TOKEN)