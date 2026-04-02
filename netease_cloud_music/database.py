from sqlalchemy import create_engine, Column, String, Integer, ForeignKey, Table, Text, BigInteger, Boolean
from sqlalchemy.orm import declarative_base, relationship, sessionmaker

Base = declarative_base()

# 关联表：用于处理 歌曲(Song) 和 歌手(Artist) 之间的多对多关系
song_artist_association = Table(
    'song_artist', Base.metadata,
    Column('song_id', String(64), ForeignKey('songs.id'), primary_key=True),
    Column('artist_id', String(64), ForeignKey('artists.id'), primary_key=True)
)

class Artist(Base):
    __tablename__ = 'artists'
    
    id = Column(String(64), primary_key=True, comment="网易云歌手ID")
    name = Column(String(255), nullable=False, comment="歌手姓名")
    
    # 关系反向引用
    songs = relationship("Song", secondary=song_artist_association, back_populates="artists")

    def __repr__(self):
        return f"<Artist(id='{self.id}', name='{self.name}')>"

class Album(Base):
    __tablename__ = 'albums'
    
    id = Column(String(64), primary_key=True, comment="网易云专辑ID")
    name = Column(String(255), nullable=False, comment="专辑名称")
    publish_time = Column(BigInteger, comment="发布时间戳")
    pic_url = Column(String(500), comment="封面图片URL")
    
    songs = relationship("Song", back_populates="album")

    def __repr__(self):
        return f"<Album(id='{self.id}', name='{self.name}')>"

class Song(Base):
    __tablename__ = 'songs'

    id = Column(String(64), primary_key=True, comment="网易云歌曲ID")
    name = Column(String(255), nullable=False, comment="歌曲名称")
    duration_ms = Column(Integer, comment="歌曲时长(毫秒)")

    # 外键关联
    album_id = Column(String(64), ForeignKey('albums.id'), nullable=True)

    # 存储字段
    lyric = Column(Text, comment="歌词内容")

    # ===== 缓存元数据字段 (v0.6.0新增) =====
    cache_level = Column(String(20), default="none", comment="缓存级别: none|basic|sampled|full")
    cache_updated_at = Column(BigInteger, nullable=True, comment="缓存最后更新时间(Unix timestamp ms)")
    api_total_comments_snapshot = Column(Integer, nullable=True, comment="API真实评论总数快照(用于计算覆盖率)")
    cache_sample_pages = Column(Text, nullable=True, comment="采样页码列表(JSON格式,如'[1,10,30]')")
    cache_freshness = Column(String(20), nullable=True, comment="缓存新鲜度: very_fresh|fresh|stale|outdated")
    last_sync_strategy = Column(String(30), nullable=True, comment="最后同步策略: full_crawl|incremental|sampled")
    
    # 关系定义
    album = relationship("Album", back_populates="songs")
    artists = relationship("Artist", secondary=song_artist_association, back_populates="songs")
    comments = relationship("Comment", back_populates="song", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Song(id='{self.id}', name='{self.name}')>"

class Comment(Base):
    __tablename__ = 'comments'

    id = Column(Integer, primary_key=True, autoincrement=True)
    comment_id = Column(String(64), unique=True, comment="网易云评论ID")
    content = Column(Text, nullable=False, comment="评论内容")
    liked_count = Column(Integer, default=0, comment="点赞数")
    time_str = Column(String(50), comment="评论时间描述")
    timestamp = Column(BigInteger, comment="评论时间戳(ms)")
    user_nickname = Column(String(255), comment="用户昵称")
    user_avatar = Column(String(500), comment="用户头像URL")

    # 软删除字段 (用于保留被平台删除的评论数据,可用于舆论审查研究)
    is_deleted = Column(Boolean, default=False, comment="是否被平台删除")
    deleted_at = Column(BigInteger, nullable=True, comment="检测到删除的时间戳(ms) - 用于分析删除时间点")
    last_seen_at = Column(BigInteger, nullable=True, comment="最后在API中出现的时间戳(ms) - 用于判断评论活跃度")

    # 外键
    song_id = Column(String(64), ForeignKey('songs.id'), nullable=False)

    # 关系
    song = relationship("Song", back_populates="comments")

    def __repr__(self):
        deleted_flag = "[已删除]" if self.is_deleted else ""
        return f"<Comment(id={self.id}, content='{self.content[:20]}...'{deleted_flag})>"

def init_db(db_path='sqlite:///music_data_v2.db'):
    """初始化数据库连接和表结构"""
    engine = create_engine(db_path, echo=False)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    return Session()
