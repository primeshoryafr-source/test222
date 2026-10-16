import discord
from discord.ext import commands
import asyncio
import sqlite3
import os
import random
import re
from datetime import datetime

# ==========================================
# ⚙️ CONFIGURATION
# ==========================================
TOKEN = 'YOUR_BOT_TOKEN' # Apna Discord bot token dalein
ADMIN_ID = 123456789012345678 # Apna Discord User ID dalein
PREFIX = '!'
MAINTENANCE_MODE = False

# Bot Setup
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix=PREFIX, intents=intents, help_command=None)

# ==========================================
# 🗄️ DATABASE SETUP
# ==========================================
def init_db():
    conn = sqlite3.connect('docker_vps.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS vps
                 (user_id TEXT, container_name TEXT, ram TEXT, cpu TEXT, status TEXT DEFAULT 'active')''')
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (user_id TEXT PRIMARY KEY, is_blacklisted INTEGER DEFAULT 0, vps_limit INTEGER DEFAULT 2)''')
    conn.commit()
    conn.close()

init_db()

# ==========================================
# 🛠️ HELPER FUNCTIONS
# ==========================================
async def run_cmd(cmd):
    proc = await asyncio.create_subprocess_shell(
        cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    stdout, stderr = await proc.communicate()
    return proc.returncode, stdout.decode().strip(), stderr.decode().strip()

def check_ownership_and_status(user_id, container_name):
    conn = sqlite3.connect('docker_vps.db')
    c = conn.cursor()
    c.execute("SELECT status FROM vps WHERE user_id=? AND container_name=?", (str(user_id), container_name))
    result = c.fetchone()
    conn.close()
    return result

def check_suspension(container_name):
    conn = sqlite3.connect('docker_vps.db')
    c = conn.cursor()
    c.execute("SELECT status FROM vps WHERE container_name=?", (container_name,))
    result = c.fetchone()
    conn.close()
    return result[0] == 'suspended' if result else False

@bot.check
async def global_checks(ctx):
    global MAINTENANCE_MODE
    if MAINTENANCE_MODE and ctx.author.id != ADMIN_ID:
        await ctx.send("🛠️ **Maintenance Mode:** The bot is currently being upgraded. Please try again later.")
        return False
        
    conn = sqlite3.connect('docker_vps.db')
    c = conn.cursor()
    c.execute("SELECT is_blacklisted FROM users WHERE user_id=?", (str(ctx.author.id),))
    res = c.fetchone()
    conn.close()
    
    if res and res[0] == 1 and ctx.author.id != ADMIN_ID:
        await ctx.send("⛔ **Blacklisted:** You have been banned from using this bot.")
        return False
    return True

# ==========================================
# 🎛️ MANAGE PANEL UI (SSHx Fixed)
# ==========================================
class ManagePanel(discord.ui.View):
    def __init__(self, container_name, user_id):
        super().__init__(timeout=None)
        self.container_name = container_name
        self.user_id = str(user_id)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if str(interaction.user.id) != self.user_id:
            await interaction.response.send_message("❌ This VPS does not belong to you!", ephemeral=True)
            return False
        
        status = check_ownership_and_status(self.user_id, self.container_name)
        if status and status[0] == 'suspended':
            await interaction.response.send_message("⛔ **This VPS is suspended.** Contact support.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Start", style=discord.ButtonStyle.success, emoji="▶️")
    async def start_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        await run_cmd(f"docker start {self.container_name}")
        await interaction.followup.send(f"✅ VPS `{self.container_name}` started!", ephemeral=True)

    @discord.ui.button(label="Stop", style=discord.ButtonStyle.danger, emoji="⏹️")
    async def stop_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        await run_cmd(f"docker stop {self.container_name}")
        await interaction.followup.send(f"🛑 VPS `{self.container_name}` stopped!", ephemeral=True)

    @discord.ui.button(label="Restart", style=discord.ButtonStyle.secondary, emoji="🔄")
    async def restart_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        await run_cmd(f"docker restart {self.container_name}")
        await interaction.followup.send(f"🔄 VPS `{self.container_name}` restarted!", ephemeral=True)

    @discord.ui.button(label="SSHx (Web)", style=discord.ButtonStyle.primary, emoji="🌐")
    async def sshx_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("⏳ Generating SSHx Web Terminal...", ephemeral=True)
        
        code, out, err = await run_cmd(f"docker inspect -f '{{{{.State.Running}}}}' {self.container_name}")
        if "true" not in out:
            return await interaction.edit_original_response(content="❌ Container is not running! Start it first.")
        
        await run_cmd(f"docker exec {self.container_name} apt-get update")
        await run_cmd(f"docker exec {self.container_name} apt-get install curl -y")
        await run_cmd(f"docker exec {self.container_name} pkill -f sshx")
        
        await run_cmd(f"docker exec -d {self.container_name} bash -c 'curl -sSf https://sshx.io/get | sh -s run > /tmp/sshx.log 2>&1'")
        
        sshx_link = None
        for _ in range(7):
            await asyncio.sleep(2)
            code, out, err = await run_cmd(f"docker exec {self.container_name} cat /tmp/sshx.log")
            
            # FIXED SSHx REGEX (Ignores color codes at the end of the URL)
            match = re.search(r'https://sshx\.io/s/[a-zA-Z0-9]+#[a-zA-Z0-9]+', out)
            if match:
                sshx_link = match.group(0)
                break
        
        if sshx_link:
            try:
                await interaction.user.send(f"🌐 **Web SSH Access for `{self.container_name}`:**\nClick here: {sshx_link}\n⚠️ *Keep this link private!*")
                await interaction.edit_original_response(content="✅ SSHx Web Terminal link sent to your DMs!")
            except discord.Forbidden:
                await interaction.edit_original_response(content="❌ Failed to send link. Enable DMs in this server!")
        else:
            await interaction.edit_original_response(content="❌ Error generating SSHx link. Make sure the container has internet access.")

class VPSDropdown(discord.ui.Select):
    def __init__(self, vps_list, user_id):
        self.user_id = str(user_id)
        options = []
        for v in vps_list:
            status_emoji = "⛔" if v[4] == 'suspended' else "🖥️"
            options.append(discord.SelectOption(label=v[1], description=f"RAM: {v[2]} | CPU: {v[3]} | Status: {v[4].capitalize()}", emoji=status_emoji))
        super().__init__(placeholder="Select a VPS to manage...", options=options)

    async def callback(self, interaction: discord.Interaction):
        container_name = self.values[0]
        status = check_ownership_and_status(self.user_id, container_name)
        if status and status[0] == 'suspended':
            return await interaction.response.send_message("⛔ **This VPS is suspended.**", ephemeral=True)
            
        view = ManagePanel(container_name, self.user_id)
        embed = discord.Embed(title=f"⚙️ Managing: {container_name}", description="Control your VPS below.", color=0x2b2d31)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

class ManageView(discord.ui.View):
    def __init__(self, vps_list, user_id):
        super().__init__(timeout=120)
        self.add_item(VPSDropdown(vps_list, user_id))

# ==========================================
# 🤖 BOT CORE & INFO COMMANDS
# ==========================================
@bot.event
async def on_ready():
    print(f'✅ Bot is ready as {bot.user}')
    await bot.change_presence(activity=discord.Game(name="!help | Enterprise VPS"))

@bot.command(name='help')
async def help_cmd(ctx):
    embed = discord.Embed(title="📚 Ultimate VPS Bot Help", color=0x5865F2)
    
    embed.add_field(name="👤 User Commands", value=
                    f"`{PREFIX}manage` / `{PREFIX}myvps` / `{PREFIX}vpsinfo`\n"
                    f"`{PREFIX}upload <vps> <path>` - Upload attached file\n"
                    f"`{PREFIX}download <vps> <path>` - Download a file\n"
                    f"`{PREFIX}speedtest <vps>` - Run internet speedtest\n"
                    f"`{PREFIX}top <vps>` - View running processes\n"
                    f"`{PREFIX}vpsip <vps>` / `{PREFIX}reinstall <vps>`\n"
                    f"`{PREFIX}transfer <vps> @user` / `{PREFIX}addsshkey <vps> <key>`\n"
                    f"`{PREFIX}logs <vps>` / `{PREFIX}renamevps <old> <new>`\n"
                    f"`{PREFIX}setpassword <vps> <pass>` / `{PREFIX}ping` / `{PREFIX}uptime`", inline=False)
    
    if ctx.author.id == ADMIN_ID:
        embed.add_field(name="🛡️ Admin Commands", value=
                        f"`{PREFIX}deploy @user <ram> <cpu>` / `{PREFIX}deletevps <vps>`\n"
                        f"`{PREFIX}clone <old> <new>` / `{PREFIX}listvps` / `{PREFIX}userinfo @user`\n"
                        f"`{PREFIX}suspend <vps>` / `{PREFIX}unsuspend <vps>`\n"
                        f"`{PREFIX}lockvps <vps>` / `{PREFIX}unlockvps <vps>`\n"
                        f"`{PREFIX}setram <vps> <ram>` / `{PREFIX}setcpu <vps> <cpu>`\n"
                        f"`{PREFIX}blacklist @user` / `{PREFIX}setlimit @user <limit>`\n"
                        f"`{PREFIX}execall <cmd>` / `{PREFIX}cmd <vps> <cmd>`\n"
                        f"`{PREFIX}purge <amount>` - Delete Discord messages\n"
                        f"`{PREFIX}maintenance <on/off>` / `{PREFIX}hoststats`\n"
                        f"`{PREFIX}broadcast <msg>` / `{PREFIX}wipeall`", inline=False)
    await ctx.send(embed=embed)

@bot.command(name='ping')
async def ping_cmd(ctx):
    await ctx.send(f"🏓 **Pong!** Bot Latency: `{round(bot.latency * 1000)}ms`")

@bot.command(name='uptime')
async def uptime_cmd(ctx):
    _, out, _ = await run_cmd("uptime -p")
    await ctx.send(f"⏱️ **Host Uptime:** `{out}`")

@bot.command(name='botinfo')
async def botinfo_cmd(ctx):
    conn = sqlite3.connect('docker_vps.db')
    c = conn.cursor()
    c.execute("SELECT COUNT(*), COUNT(DISTINCT user_id) FROM vps")
    res = c.fetchone()
    conn.close()
    embed = discord.Embed(title="🤖 Bot Information", color=0x3498db)
    embed.add_field(name="Total VPS", value=f"`{res[0]}`", inline=True)
    embed.add_field(name="Total Clients", value=f"`{res[1]}`", inline=True)
    embed.add_field(name="Maintenance Mode", value=f"`{'ON' if MAINTENANCE_MODE else 'OFF'}`", inline=False)
    await ctx.send(embed=embed)

# ==========================================
# 👤 USER COMMANDS
# ==========================================

@bot.command(name='upload')
async def upload_file(ctx, container_name: str, remote_path: str = "/root/"):
    status = check_ownership_and_status(ctx.author.id, container_name)
    if not status: return await ctx.send("❌ VPS not found or you don't own it.")
    if status[0] == 'suspended': return await ctx.send("⛔ VPS is suspended.")
    
    if not ctx.message.attachments: return await ctx.send("❌ You need to attach a file to the message!")
    
    file = ctx.message.attachments[0]
    local_path = f"/tmp/{file.filename}"
    await file.save(local_path)
    
    msg = await ctx.send(f"⏳ Uploading `{file.filename}` to `{container_name}:{remote_path}`...")
    code, out, err = await run_cmd(f"docker cp {local_path} {container_name}:{remote_path}")
    os.remove(local_path)
    
    if code == 0: await msg.edit(content=f"✅ **File Uploaded!** Saved to `{remote_path}` in `{container_name}`.")
    else: await msg.edit(content=f"❌ **Upload Failed:**\n```bash\n{err}\n```")

@bot.command(name='download')
async def download_file(ctx, container_name: str, file_path: str):
    status = check_ownership_and_status(ctx.author.id, container_name)
    if not status: return await ctx.send("❌ VPS not found or you don't own it.")
    if status[0] == 'suspended': return await ctx.send("⛔ VPS is suspended.")

    local_path = f"/tmp/dl_{os.path.basename(file_path)}"
    msg = await ctx.send("⏳ Fetching file from VPS...")
    
    code, out, err = await run_cmd(f"docker cp {container_name}:{file_path} {local_path}")
    
    if code == 0:
        if os.path.getsize(local_path) > 25 * 1024 * 1024:
            os.remove(local_path)
            return await msg.edit(content="❌ File is too large to send via Discord (Limit: 25MB).")
        await ctx.send(file=discord.File(local_path))
        await msg.delete()
        os.remove(local_path)
    else:
        await msg.edit(content=f"❌ **Download Failed**:\n```bash\n{err}\n```")

@bot.command(name='speedtest')
async def speedtest_cmd(ctx, container_name: str):
    status = check_ownership_and_status(ctx.author.id, container_name)
    if not status: return await ctx.send("❌ VPS not found or you don't own it.")
    
    msg = await ctx.send("⏳ Running network speedtest inside the VPS... (Takes ~20 seconds)")
    await run_cmd(f"docker exec {container_name} apt-get update")
    await run_cmd(f"docker exec -e DEBIAN_FRONTEND=noninteractive {container_name} apt-get install speedtest-cli -y")
    code, out, err = await run_cmd(f"docker exec {container_name} speedtest-cli --simple")
    
    if code == 0: await msg.edit(content=f"🚀 **Speedtest Results for `{container_name}`:**\n```yaml\n{out}\n```")
    else: await msg.edit(content="❌ Failed to run speedtest.")

@bot.command(name='top')
async def top_cmd(ctx, container_name: str):
    status = check_ownership_and_status(ctx.author.id, container_name)
    if not status: return await ctx.send("❌ VPS not found or you don't own it.")
    
    code, out, err = await run_cmd(f"docker exec {container_name} ps -eo pid,user,%mem,%cpu,comm --sort=-%mem | head -n 15")
    if code == 0: await ctx.send(f"📊 **Top Processes in `{container_name}`:**\n```bash\n{out}\n```")
    else: await ctx.send("❌ Could not fetch processes. Ensure the container is running.")

@bot.command(name='manage')
async def manage_vps(ctx):
    conn = sqlite3.connect('docker_vps.db')
    c = conn.cursor()
    c.execute("SELECT * FROM vps WHERE user_id=?", (str(ctx.author.id),))
    vps_list = c.fetchall()
    conn.close()
    if not vps_list: return await ctx.send("❌ You do not own any VPS.")
    embed = discord.Embed(title="🖥️ VPS Management Dashboard", description="Select your VPS from the dropdown.", color=0x3498db)
    await ctx.send(embed=embed, view=ManageView(vps_list, ctx.author.id))

@bot.command(name='myvps')
async def my_vps(ctx):
    conn = sqlite3.connect('docker_vps.db')
    c = conn.cursor()
    c.execute("SELECT container_name, ram, cpu, status FROM vps WHERE user_id=?", (str(ctx.author.id),))
    vps_list = c.fetchall()
    conn.close()
    if not vps_list: return await ctx.send("❌ You don't own any VPS.")
    embed = discord.Embed(title=f"📦 {ctx.author.name}'s Inventory", color=0x2ecc71)
    for v in vps_list:
        embed.add_field(name=f"🖥️ {v[0]}", value=f"**RAM:** {v[1]} | **CPU:** {v[2]}\n**Status:** {v[3].capitalize()}", inline=False)
    await ctx.send(embed=embed)

@bot.command(name='reinstall')
async def reinstall_vps(ctx, container_name: str):
    conn = sqlite3.connect('docker_vps.db')
    c = conn.cursor()
    c.execute("SELECT ram, cpu, status FROM vps WHERE user_id=? AND container_name=?", (str(ctx.author.id), container_name))
    result = c.fetchone()
    conn.close()

    if not result: return await ctx.send("❌ VPS not found.")
    if result[2] == 'suspended': return await ctx.send("⛔ VPS is suspended.")

    msg = await ctx.send(f"⏳ **Reinstalling `{container_name}`...** All data will be wiped.")
    await run_cmd(f"docker stop {container_name}")
    await run_cmd(f"docker rm {container_name}")
    
    cmd = f"docker run -itd --name {container_name} --memory {result[0]} --memory-swap {result[0]} --cpus {result[1]} ubuntu-vps:latest /bin/bash"
    code, out, err = await run_cmd(cmd)
    
    if code == 0:
        await run_cmd(f"docker exec -e DEBIAN_FRONTEND=noninteractive {container_name} apt-get update && apt-get install curl wget sudo nano -y")
        await msg.edit(content=f"✅ **Reinstallation Complete!**")
    else: await msg.edit(content=f"❌ **Failed:**\n```bash\n{err}\n```")

@bot.command(name='transfer')
async def transfer_vps(ctx, container_name: str, new_owner: discord.Member):
    conn = sqlite3.connect('docker_vps.db')
    c = conn.cursor()
    c.execute("SELECT status FROM vps WHERE user_id=? AND container_name=?", (str(ctx.author.id), container_name))
    if not c.fetchone(): return await ctx.send("❌ VPS not found.")
    
    c.execute("UPDATE vps SET user_id=? WHERE container_name=?", (str(new_owner.id), container_name))
    conn.commit()
    conn.close()
    await ctx.send(f"✅ Transferred `{container_name}` to {new_owner.mention}.")
    try: await new_owner.send(f"🎁 **VPS Transferred!** {ctx.author.name} has given you ownership of VPS `{container_name}`.")
    except: pass

@bot.command(name='addsshkey')
async def add_ssh_key(ctx, container_name: str, *, ssh_key: str):
    if not check_ownership_and_status(ctx.author.id, container_name): return await ctx.send("❌ Error.")
    await run_cmd(f"docker exec {container_name} mkdir -p /root/.ssh")
    await run_cmd(f"docker exec {container_name} bash -c \"echo '{ssh_key}' >> /root/.ssh/authorized_keys\"")
    await run_cmd(f"docker exec {container_name} chmod 600 /root/.ssh/authorized_keys")
    await ctx.send(f"✅ SSH Key added to `{container_name}`.")

@bot.command(name='vpsip')
async def vps_ip(ctx, container_name: str):
    if not check_ownership_and_status(ctx.author.id, container_name): return await ctx.send("❌ VPS not found.")
    code, out, err = await run_cmd(f"docker inspect -f '{{{{range.NetworkSettings.Networks}}}}{{{{.IPAddress}}}}{{{{end}}}}' {container_name}")
    if out: await ctx.send(f"🌐 Internal Network IP for `{container_name}` is: **{out}**")
    else: await ctx.send("❌ Could not fetch IP.")

@bot.command(name='setpassword')
async def set_password(ctx, container_name: str, new_password: str):
    if not check_ownership_and_status(ctx.author.id, container_name): return await ctx.send("❌ VPS not found.")
    code, out, err = await run_cmd(f"docker exec {container_name} sh -c \"echo 'root:{new_password}' | chpasswd\"")
    if code == 0:
        await ctx.send("✅ Root password updated.")
        try: await ctx.message.delete()
        except: pass
    else: await ctx.send(f"❌ Failed.\n```bash\n{err}\n```")

@bot.command(name='vpsinfo')
async def vps_info(ctx):
    conn = sqlite3.connect('docker_vps.db')
    c = conn.cursor()
    c.execute("SELECT container_name FROM vps WHERE user_id=?", (str(ctx.author.id),))
    vps_list = c.fetchall()
    conn.close()
    if not vps_list: return await ctx.send("❌ No VPS owned.")

    embed = discord.Embed(title="📊 Live VPS Status", color=0x9b59b6)
    msg = await ctx.send("Fetching...")
    for v in vps_list:
        code, out, err = await run_cmd(f"docker stats --no-stream --format 'RAM: {{{{ .MemUsage }}}} | CPU: {{{{ .CPUPerc }}}}' {v[0]}")
        if code == 0: embed.add_field(name=f"🖥️ {v[0]}", value=f"🟢 Running\n{out}", inline=False)
        else: embed.add_field(name=f"🖥️ {v[0]}", value="🔴 Stopped/Suspended", inline=False)
    await msg.edit(content=None, embed=embed)

@bot.command(name='logs')
async def get_logs(ctx, container_name: str):
    if not check_ownership_and_status(ctx.author.id, container_name): return await ctx.send("❌ VPS not found.")
    code, out, err = await run_cmd(f"docker logs --tail 20 {container_name}")
    log_data = (err if err else out)[-1900:]
    await ctx.send(f"📜 **Logs for `{container_name}`:**\n```bash\n{log_data}\n```")

@bot.command(name='renamevps')
async def rename_vps(ctx, old_name: str, new_name: str):
    conn = sqlite3.connect('docker_vps.db')
    c = conn.cursor()
    c.execute("SELECT * FROM vps WHERE user_id=? AND container_name=?", (str(ctx.author.id), old_name))
    if not c.fetchone():
        conn.close()
        return await ctx.send("❌ VPS not found or you don't own it.")
    
    if not new_name.isalnum() and "-" not in new_name: return await ctx.send("❌ Invalid name! Use only letters, numbers, and dashes.")

    code, out, err = await run_cmd(f"docker rename {old_name} {new_name}")
    if code == 0:
        c.execute("UPDATE vps SET container_name=? WHERE container_name=?", (new_name, old_name))
        conn.commit()
        await ctx.send(f"✅ Your VPS has been renamed from `{old_name}` to `{new_name}`.")
    else: await ctx.send(f"❌ Failed to rename.\n```bash\n{err}\n```")
    conn.close()

# ==========================================
# 🛡️ ADMIN COMMANDS
# ==========================================

@bot.command(name='purge')
@commands.has_permissions(manage_messages=True)
async def purge_msgs(ctx, amount: int):
    if ctx.author.id != ADMIN_ID: return await ctx.send("❌ Restricted.")
    await ctx.channel.purge(limit=amount + 1)
    msg = await ctx.send(f"🧹 Purged {amount} messages.")
    await asyncio.sleep(3)
    await msg.delete()

@bot.command(name='lockvps')
async def lock_vps(ctx, container_name: str):
    if ctx.author.id != ADMIN_ID: return await ctx.send("❌ Restricted.")
    await run_cmd(f"docker pause {container_name}")
    await ctx.send(f"⏸️ `{container_name}` has been paused (locked).")

@bot.command(name='unlockvps')
async def unlock_vps(ctx, container_name: str):
    if ctx.author.id != ADMIN_ID: return await ctx.send("❌ Restricted.")
    await run_cmd(f"docker unpause {container_name}")
    await ctx.send(f"▶️ `{container_name}` has been unpaused.")

@bot.command(name='deploy')
async def deploy_vps(ctx, member: discord.Member, ram: str, cpu: str):
    if ctx.author.id != ADMIN_ID: return await ctx.send("❌ Restricted to Admins!")
    if ram.isdigit(): ram += "g"
    container_name = f"vps-{member.id}-{random.randint(1000, 9999)}"
    msg = await ctx.send(embed=discord.Embed(title="⏳ Deploying VPS...", color=0xf1c40f))

    cmd = f"docker run -itd --name {container_name} --memory {ram} --memory-swap {ram} --cpus {cpu} ubuntu-vps:latest /bin/bash"
    code, out, err = await run_cmd(cmd)

    if code == 0:
        conn = sqlite3.connect('docker_vps.db')
        c = conn.cursor()
        c.execute("INSERT INTO vps VALUES (?, ?, ?, ?, ?)", (str(member.id), container_name, ram, cpu, 'active'))
        conn.commit()
        conn.close()

        await run_cmd(f"docker exec -e DEBIAN_FRONTEND=noninteractive {container_name} apt-get update && apt-get install curl wget sudo nano -y")
        
        embed = discord.Embed(title="✅ VPS Deployed Successfully!", color=0x2ecc71)
        embed.add_field(name="Owner", value=member.mention)
        embed.add_field(name="Container", value=f"`{container_name}`")
        await msg.edit(embed=embed)
        try: await member.send(f"🎉 Your VPS `{container_name}` is ready! Type `!manage` in the server.")
        except: pass 
    else: await msg.edit(content=f"❌ Error:\n```bash\n{err}\n```", embed=None)

@bot.command(name='deletevps')
async def delete_vps(ctx, container_name: str):
    if ctx.author.id != ADMIN_ID: return await ctx.send("❌ Restricted!")
    msg = await ctx.send(f"⏳ Deleting `{container_name}`...")
    await run_cmd(f"docker stop {container_name}")
    await run_cmd(f"docker rm {container_name}")
    conn = sqlite3.connect('docker_vps.db')
    c = conn.cursor()
    c.execute("DELETE FROM vps WHERE container_name=?", (container_name,))
    conn.commit()
    conn.close()
    await msg.edit(content=f"🗑️ Deleted VPS `{container_name}`.")

@bot.command(name='suspend')
async def suspend_vps(ctx, container_name: str):
    if ctx.author.id != ADMIN_ID: return
    conn = sqlite3.connect('docker_vps.db')
    c = conn.cursor()
    c.execute("UPDATE vps SET status='suspended' WHERE container_name=?", (container_name,))
    conn.commit()
    conn.close()
    await run_cmd(f"docker stop {container_name}")
    await ctx.send(f"⛔ `{container_name}` Suspended.")

@bot.command(name='unsuspend')
async def unsuspend_vps(ctx, container_name: str):
    if ctx.author.id != ADMIN_ID: return
    conn = sqlite3.connect('docker_vps.db')
    c = conn.cursor()
    c.execute("UPDATE vps SET status='active' WHERE container_name=?", (container_name,))
    conn.commit()
    conn.close()
    await run_cmd(f"docker start {container_name}")
    await ctx.send(f"✅ `{container_name}` Unsuspended.")

@bot.command(name='setram')
async def set_ram(ctx, container_name: str, ram: str):
    if ctx.author.id != ADMIN_ID: return
    if ram.isdigit(): ram += "g"
    await run_cmd(f"docker update --memory {ram} --memory-swap {ram} {container_name}")
    await ctx.send(f"✅ RAM for `{container_name}` set to **{ram}**.")

@bot.command(name='setcpu')
async def set_cpu(ctx, container_name: str, cpu: str):
    if ctx.author.id != ADMIN_ID: return
    await run_cmd(f"docker update --cpus {cpu} {container_name}")
    await ctx.send(f"✅ CPU for `{container_name}` set to **{cpu}**.")

@bot.command(name='listvps')
async def list_vps(ctx):
    if ctx.author.id != ADMIN_ID: return
    conn = sqlite3.connect('docker_vps.db')
    c = conn.cursor()
    c.execute("SELECT * FROM vps")
    all_vps = c.fetchall()
    conn.close()
    if not all_vps: return await ctx.send("ℹ️ No VPS instances deployed.")
    embed = discord.Embed(title="📋 Deployed Instances", color=0xe67e22)
    for v in all_vps:
        user = bot.get_user(int(v[0]))
        embed.add_field(name=f"📦 {v[1]}", value=f"👤 {user} | 💾 {v[2]} | ⚙️ {v[3]} | 📌 {v[4]}", inline=False)
    await ctx.send(embed=embed)

@bot.command(name='hoststats')
async def host_stats(ctx):
    if ctx.author.id != ADMIN_ID: return
    _, mem, _ = await run_cmd("free -m | awk 'NR==2{print $3\"/\"$2\"MB\"}'")
    _, cpu, _ = await run_cmd("top -bn1 | grep load | awk '{print $(NF-2)}'")
    _, disk, _ = await run_cmd("df -h / | awk '$NF==\"/\"{print $3\"/\"$2}'")
    embed = discord.Embed(title="🌐 Host Stats", color=0x1abc9c)
    embed.add_field(name="RAM", value=mem)
    embed.add_field(name="CPU Load", value=cpu)
    embed.add_field(name="Disk", value=disk)
    await ctx.send(embed=embed)

@bot.command(name='wipeall')
async def wipe_all(ctx):
    if ctx.author.id != ADMIN_ID: return await ctx.send("❌ Restricted to Admins!")
    msg = await ctx.send("⏳ **WARNING: Wiping ALL VPS containers...**")
    conn = sqlite3.connect('docker_vps.db')
    c = conn.cursor()
    c.execute("SELECT container_name FROM vps")
    for v in c.fetchall():
        await run_cmd(f"docker stop {v[0]}")
        await run_cmd(f"docker rm {v[0]}")
    c.execute("DELETE FROM vps")
    conn.commit()
    conn.close()
    await msg.edit(content="💥 **System Wiped:** All VPS instances have been completely deleted.")

@bot.command(name='maintenance')
async def toggle_maintenance(ctx, state: str):
    if ctx.author.id != ADMIN_ID: return await ctx.send("❌ Restricted to Admins!")
    global MAINTENANCE_MODE
    if state.lower() == "on":
        MAINTENANCE_MODE = True
        await ctx.send("🛠️ **Maintenance Mode ON:** All users are now locked out.")
    elif state.lower() == "off":
        MAINTENANCE_MODE = False
        await ctx.send("✅ **Maintenance Mode OFF:** Users can now use the bot.")
    else: await ctx.send("Use `!maintenance on` or `!maintenance off`")

@bot.command(name='clone')
async def clone_vps(ctx, container_name: str, new_name: str):
    if ctx.author.id != ADMIN_ID: return await ctx.send("❌ Restricted to Admins!")
    conn = sqlite3.connect('docker_vps.db')
    c = conn.cursor()
    c.execute("SELECT user_id, ram, cpu FROM vps WHERE container_name=?", (container_name,))
    result = c.fetchone()
    if not result:
        conn.close()
        return await ctx.send("❌ Source VPS not found in database.")
    user_id, ram, cpu = result
    
    msg = await ctx.send(f"⏳ **Cloning `{container_name}` to `{new_name}`...**")
    await run_cmd(f"docker commit {container_name} temp_clone_img")
    code, out, err = await run_cmd(f"docker run -itd --name {new_name} --memory {ram} --memory-swap {ram} --cpus {cpu} temp_clone_img /bin/bash")
    await run_cmd("docker rmi temp_clone_img")
    
    if code == 0:
        c.execute("INSERT INTO vps VALUES (?, ?, ?, ?, ?)", (user_id, new_name, ram, cpu, 'active'))
        conn.commit()
        await msg.edit(content=f"✅ **Successfully cloned!** The new VPS `{new_name}` has been assigned to the same owner.")
    else: await msg.edit(content=f"❌ **Clone Failed:**\n```bash\n{err}\n```")
    conn.close()

@bot.command(name='execall')
async def exec_all(ctx, *, command: str):
    if ctx.author.id != ADMIN_ID: return await ctx.send("❌ Restricted to Admins!")
    conn = sqlite3.connect('docker_vps.db')
    c = conn.cursor()
    c.execute("SELECT container_name FROM vps")
    containers = c.fetchall()
    conn.close()
    
    msg = await ctx.send(f"⏳ Executing command on {len(containers)} containers...")
    success, fail = 0, 0
    for v in containers:
        code, _, _ = await run_cmd(f"docker exec -d {v[0]} sh -c '{command}'")
        if code == 0: success += 1
        else: fail += 1
    await msg.edit(content=f"✅ **Mass Execution Complete:**\nSuccessfully ran on {success} containers. (Failed on {fail}).")

@bot.command(name='broadcast')
async def broadcast_msg(ctx, *, message: str):
    if ctx.author.id != ADMIN_ID: return await ctx.send("❌ Restricted to Admins!")
    conn = sqlite3.connect('docker_vps.db')
    c = conn.cursor()
    c.execute("SELECT DISTINCT user_id FROM vps")
    users = c.fetchall()
    conn.close()

    success, fail = 0, 0
    await ctx.send("📢 Broadcasting message to all VPS owners...")
    embed = discord.Embed(title="📢 Admin Announcement", description=message, color=0xe74c3c)
    
    for u in users:
        try:
            member = bot.get_user(int(u[0])) or await bot.fetch_user(int(u[0]))
            await member.send(embed=embed)
            success += 1
        except: fail += 1
    await ctx.send(f"✅ **Broadcast Complete!** Sent to {success} users. (Failed: {fail})")

@bot.command(name='blacklist')
async def blacklist_user(ctx, member: discord.Member):
    if ctx.author.id != ADMIN_ID: return await ctx.send("❌ Restricted to Admins!")
    conn = sqlite3.connect('docker_vps.db')
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO users (user_id, is_blacklisted) VALUES (?, 1)", (str(member.id),))
    conn.commit()
    conn.close()
    await ctx.send(f"⛔ {member.mention} has been **blacklisted** from using this bot.")

@bot.command(name='unblacklist')
async def unblacklist_user(ctx, member: discord.Member):
    if ctx.author.id != ADMIN_ID: return await ctx.send("❌ Restricted to Admins!")
    conn = sqlite3.connect('docker_vps.db')
    c = conn.cursor()
    c.execute("UPDATE users SET is_blacklisted=0 WHERE user_id=?", (str(member.id),))
    conn.commit()
    conn.close()
    await ctx.send(f"✅ {member.mention} has been removed from the blacklist.")

@bot.command(name='setlimit')
async def set_limit(ctx, member: discord.Member, limit: int):
    if ctx.author.id != ADMIN_ID: return await ctx.send("❌ Restricted to Admins!")
    conn = sqlite3.connect('docker_vps.db')
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO users (user_id, vps_limit) VALUES (?, ?)", (str(member.id), limit))
    conn.commit()
    conn.close()
    await ctx.send(f"✅ {member.mention}'s maximum VPS limit has been set to **{limit}**.")

@bot.command(name='forcepass')
async def force_pass(ctx, container_name: str, new_password: str):
    if ctx.author.id != ADMIN_ID: return await ctx.send("❌ Restricted to Admins!")
    code, out, err = await run_cmd(f"docker exec {container_name} sh -c \"echo 'root:{new_password}' | chpasswd\"")
    if code == 0:
        await ctx.send(f"✅ Root password for `{container_name}` has been forcefully updated.")
        try: await ctx.message.delete()
        except: pass
    else: await ctx.send(f"❌ Failed to change password.\n```bash\n{err}\n```")

@bot.command(name='backup')
async def backup_vps(ctx, container_name: str):
    if ctx.author.id != ADMIN_ID: return await ctx.send("❌ Restricted to Admins!")
    date_str = datetime.now().strftime("%Y%m%d-%H%M")
    backup_name = f"backup-{container_name}-{date_str}"
    msg = await ctx.send(f"⏳ Creating snapshot image for `{container_name}`... This may take a while.")
    code, out, err = await run_cmd(f"docker commit {container_name} {backup_name}")
    if code == 0: await msg.edit(content=f"💾 **Backup Complete!**\nSnapshot saved as Docker Image: `{backup_name}`")
    else: await msg.edit(content=f"❌ **Backup Failed:**\n```bash\n{err}\n```")

@bot.command(name='userinfo')
async def user_info(ctx, member: discord.Member):
    if ctx.author.id != ADMIN_ID: return await ctx.send("❌ Restricted to Admins!")
    conn = sqlite3.connect('docker_vps.db')
    c = conn.cursor()
    c.execute("SELECT container_name, ram, cpu, status FROM vps WHERE user_id=?", (str(member.id),))
    vps_list = c.fetchall()
    c.execute("SELECT is_blacklisted, vps_limit FROM users WHERE user_id=?", (str(member.id),))
    user_settings = c.fetchone()
    conn.close()

    bl = "Yes" if user_settings and user_settings[0] == 1 else "No"
    limit = user_settings[1] if user_settings else 2

    embed = discord.Embed(title=f"👤 Info for {member.name}", description=f"**Blacklisted:** {bl} | **VPS Limit:** {limit}", color=0x9b59b6)
    if not vps_list: embed.add_field(name="Servers", value="User has no VPS.")
    else:
        for v in vps_list: embed.add_field(name=f"🖥️ {v[0]}", value=f"RAM: {v[1]} | CPU: {v[2]} | Status: {v[3].capitalize()}", inline=False)
    await ctx.send(embed=embed)

@bot.command(name='cmd')
async def execute_command(ctx, container_name: str, *, command: str):
    if ctx.author.id != ADMIN_ID: return await ctx.send("❌ Restricted to Admins!")
    code, out, err = await run_cmd(f"docker exec {container_name} sh -c '{command}'")
    result = out if out else err
    if len(result) > 1900: result = result[-1900:]
    await ctx.send(f"💻 **Output from `{container_name}`:**\n```bash\n{result if result else 'Command executed without output.'}\n```")

# Run the Bot
bot.run(TOKEN)