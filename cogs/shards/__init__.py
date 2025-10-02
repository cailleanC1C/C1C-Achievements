from .cog import ShardsCog

async def setup(bot):
    await bot.add_cog(ShardsCog(bot))

