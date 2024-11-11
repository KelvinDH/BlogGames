# app.py
from flask import Flask, render_template, request, redirect, url_for, jsonify, flash
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin, LoginManager, login_user, login_required, logout_user, current_user
from datetime import datetime
from flask_ckeditor import CKEditor, CKEditorField
from werkzeug.utils import secure_filename
import os
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail
import bleach
from wtforms.validators import DataRequired
from flask_wtf import FlaskForm
from wtforms import StringField, SubmitField
from flask_migrate import Migrate
import re
from sqlalchemy import func

app = Flask(__name__)

# Configuração do CKEditor
# Configuração de pasta de upload
UPLOAD_FOLDER = 'static/uploads'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # Limite de 16 MB para upload

# Certifique-se de que a pasta de upload existe
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
SENDGRID_API_KEY = os.getenv('SENDGRID_API_KEY')


# Define uma chave secreta para o gerenciamento de sessões
app.secret_key = 'sua_chave_secreta_unica'  # Substitua por uma string secreta e complexa
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///blog.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)
migrate = Migrate(app, db)


# Configuração do Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# Configurações globais para o autor
AUTHOR_NAME = "Kelvin"
AUTHOR_BIO = "Esta é a biografia padrão do autor. Aqui você pode contar um pouco sobre você ou sobre o propósito do blog."
AUTHOR_IMAGE = "images/author1.png"  # Caminho para a imagem do autor

# Modelo de Usuário
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password = db.Column(db.String(50), nullable=False)  # Nota: Melhor usar hash para senha em produção.

# Definindo o formulário com o CKEditorField
class PostForm(FlaskForm):
    title = StringField('Título', validators=[DataRequired()])
    content = CKEditorField('Conteúdo', validators=[DataRequired()])
    submit = SubmitField('Publicar')    

# Modelo de Métricas do Site
class SiteMetrics(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    total_visits = db.Column(db.Integer, default=0)

@app.template_filter('regex_search')
def regex_search(value, pattern, group=0):
    """Extract a match using a regular expression."""
    match = re.search(pattern, value)
    if match:
        return match.group(group)
    return None    

def sanitize_content(content):
    # Definir as tags permitidas
    allowed_tags = ['p', 'b', 'i', 'u', 'strong', 'em', 'ul', 'ol', 'li', 'a', 'span']
    #content = sanitize_content(request.form['content'])
    
    # Definir os atributos permitidos para cada tag
    allowed_attributes = {
        'a': ['href', 'title'],
        'img': ['src', 'alt', 'width', 'height'],
    }
    
    # Sanitizar o conteúdo com bleach
    return bleach.clean(content, tags=allowed_tags, attributes=allowed_attributes, strip=True)

# Endpoint para upload de imagem
@app.route('/upload', methods=['POST'])
@login_required
def upload_image():
    file = request.files.get('upload')
    if not file:
        return jsonify({'error': 'Nenhum arquivo enviado'}), 400

    # Salva o arquivo com um nome seguro
    filename = secure_filename(file.filename)
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    
    try:
            # Salva o arquivo
            file.save(filepath)
    except Exception as e:
            print(f"Erro ao salvar a imagem: {e}")
            return {'error': 'Erro ao salvar a imagem'}, 500


    # Retorna a URL da imagem para ser usada pelo Summernote
    return jsonify({'url': url_for('static', filename=f'uploads/{filename}', _external=True)}), 200

# Carregar usuário
@login_manager.user_loader
def load_user(user_id):
      return db.session.get(User, int(user_id))

# Criar usuário padrão (admin)
def create_admin():
    admin = User.query.filter_by(username='admin').first()
    if not admin:
        admin = User(username='admin', password='admin123')  # Configure a senha inicial
        db.session.add(admin)
        db.session.commit()


# Modelo do Post
class Post(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    content = db.Column(db.Text, nullable=False)
    featured_image = db.Column(db.String(200), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    views = db.Column(db.Integer, default=0)  # Campo para contagem de visualizações do post
    author_name = db.Column(db.String(100), nullable=False, default='Kelvin')
    author_bio = db.Column(db.Text, nullable=False, default='Esta é a biografia padrão do autor. Aqui você pode contar um pouco sobre você ou sobre o propósito do blog.')
    author_image = db.Column(db.String(200), nullable=True)  # URL da imagem do autor

class Comment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(db.Integer, db.ForeignKey('post.id'), nullable=False)  # Referência ao Post
    name = db.Column(db.String(50), nullable=False)
    text = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relacionamento com Post
    post = db.relationship('Post', backref=db.backref('comments', lazy=True))    

@app.route('/post/<int:post_id>/add_comment', methods=['POST'])
def add_comment(post_id):
    post = Post.query.get_or_404(post_id)  # Verifica se o post existe
    name = request.form.get('name')  # Obtém o nome do formulário
    text = request.form.get('text')  # Obtém o texto do formulário

    if not name or not text:
        # Caso o nome ou o texto esteja vazio, redireciona de volta com uma mensagem de erro
        flash("Nome e comentário são obrigatórios.", "danger")
        return redirect(url_for('post_detail', post_id=post.id))
    
    new_comment = Comment(name=name, text=text, post=post)
    db.session.add(new_comment)
    db.session.commit()

    # Confirmação no console
    print("Comentário salvo:", new_comment.name, new_comment.text, "para o post_id:", new_comment.post_id)
    return redirect(url_for('post_detail', post_id=post.id))

@app.route('/post/<int:post_id>/comments', methods=['GET'])
def get_comments(post_id):
    page = request.args.get('page', 1, type=int)
    comments = Comment.query.filter_by(post_id=post_id).order_by(Comment.created_at.desc()).paginate(page=page, per_page=10, error_out=False)
    
    # Extrai os comentários paginados para uma lista
    comments_list = [{
        'name': comment.name,
        'text': comment.text,
        'created_at': comment.created_at.strftime('%d/%m/%Y %H:%M')
    } for comment in comments.items]

    # Retorna os comentários e uma flag indicando se há mais páginas
    return jsonify({
        'comments': comments_list,
        'has_more': comments.has_next
    })

@app.route('/about')
def about():
    return render_template('about.html')



@app.route('/contact', methods=['GET', 'POST'])
def contact():
    if request.method == 'POST':
        name = request.form['name']
        email = request.form['email']
        message = request.form['message']
        
        # Cria a mensagem de e-mail usando o SendGrid
        subject = f"Nova mensagem de {name}"
        to_email = 'klassicgamess@gmail.com'
        from_email = 'kelvin.dh@hotmail.com'  # Deve ser um e-mail verificado no SendGrid
        content = f"Nome: {name}\nEmail: {email}\n\nMensagem:\n{message}"

        # Configura a mensagem com o SendGrid
        mail = Mail(
            from_email=from_email,
            to_emails=to_email,
            subject=subject,
            plain_text_content=content
        )

        try:
            # Envia o e-mail com o SendGrid
            sg = SendGridAPIClient(SENDGRID_API_KEY)
            response = sg.send(mail)
            flash("Mensagem enviada com sucesso!", "success")
            return redirect(url_for('contact'))
        except Exception as e:
            flash("Ocorreu um erro ao enviar a mensagem. Tente novamente.", "danger")
            print(f"Erro ao enviar e-mail: {e}")
            return redirect(url_for('contact'))

    return render_template('contact.html')

# Página Principal
@app.route('/')
def index():
    # Incrementar o contador de visitas totais na primeira visita
    site_metrics = SiteMetrics.query.first()
    if not site_metrics:
        site_metrics = SiteMetrics(total_visits=1)
        db.session.add(site_metrics)
    else:
        site_metrics.total_visits += 1
    db.session.commit()
    
    # Parâmetro de página (começa com 1)
    page = request.args.get('page', 1, type=int)
    per_page = 5  # Número de postagens por página
    
    # Consulta paginada para as postagens
    posts = Post.query.order_by(Post.created_at.desc()).paginate(page=page, per_page=per_page, error_out=False)
    
    # Verifica se há uma próxima página para exibir o botão "Ver Mais"
    has_more_posts = posts.has_next
    next_page = page + 1 if has_more_posts else None
    
    # Posts recentes para exibir na barra lateral ou em outras seções
    recent_posts = Post.query.order_by(Post.created_at.desc()).limit(5).all()

    return render_template(
        'index.html', 
        posts=posts.items, 
        recent_posts=recent_posts, 
        has_more_posts=has_more_posts, 
        next_page=next_page
    )


# Rota de Login
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        user = User.query.filter_by(username=username).first()
        
        # Verificação simples de usuário e senha
        if user and user.password == password:
            login_user(user)
            return redirect(url_for('admin'))
        else:
            return "Usuário ou senha incorretos. Tente novamente."
    
    return render_template('login.html')

@app.route('/search')
def search():
    query = request.args.get('query', '').strip()  # Pega o termo de busca

    if query:
        # Filtra as postagens pelo título ou conteúdo usando "LIKE"
        results = Post.query.filter(
            (Post.title.ilike(f'%{query}%')) | (Post.content.ilike(f'%{query}%'))
        ).order_by(Post.created_at.desc()).all()
    else:
        # Se a consulta estiver vazia, retorna uma lista vazia
        results = []

    return render_template('search_results.html', query=query, results=results)


# Página de Administração: Lista de Posts
@app.route('/admin')
@login_required
def admin():
    # Parâmetros de busca e paginação
    search_id = request.args.get('search_id', type=int)  # Captura o número da postagem para busca
    page = request.args.get('page', 1, type=int)  # Captura o número da página para paginação
    per_page = 20  # Número máximo de postagens por página

    # Realiza a busca por ID de postagem ou consulta todas as postagens
    if search_id:
        # Filtra por ID da postagem
        posts = Post.query.filter_by(id=search_id).paginate(page=page, per_page=per_page, error_out=False)
    else:
        # Exibe todas as postagens com paginação
        posts = Post.query.order_by(Post.created_at.desc()).paginate(page=page, per_page=per_page, error_out=False)

    return render_template(
        'admin.html',
        posts=posts.items,  # Lista de postagens para a página atual
        pagination=posts  # Objeto de paginação para controle de navegação
    )


# Rota de Logout
@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/metrics')
@login_required
def metrics():
    # Consulta para obter todas as postagens com contagem de visualizações e comentários
    posts = db.session.query(
        Post.id,
        Post.title,
        Post.views,
        func.count(Comment.id).label('comment_count')
    ).outerjoin(Comment).group_by(Post.id).order_by(Post.created_at.desc()).all()
    
    # Consulta para métricas gerais do site
    site_metrics = SiteMetrics.query.first()
    total_visits = site_metrics.total_visits if site_metrics else 0

    return render_template('metrics.html', posts=posts, total_visits=total_visits)

@app.route('/admin/posts')
@login_required
def admin_posts():
    # Captura os parâmetros de busca por ID e por título, e o número da página para paginação
    search_id = request.args.get('search_id', type=int)
    search_title = request.args.get('search_title', '').strip()
    page = request.args.get('page', 1, type=int)
    per_page = 20  # Número máximo de postagens por página

    # Se um ID de postagem foi fornecido, busca por ID específico
    if search_id:
        posts = Post.query.filter_by(id=search_id).paginate(page=page, per_page=per_page, error_out=False)
    elif search_title:
        # Se um título foi fornecido, busca postagens que contenham o título
        posts = Post.query.filter(Post.title.ilike(f'%{search_title}%')).order_by(Post.created_at.desc()).paginate(page=page, per_page=per_page, error_out=False)
    else:
        # Caso nenhuma busca tenha sido realizada, exibe todas as postagens
        posts = Post.query.order_by(Post.created_at.desc()).paginate(page=page, per_page=per_page, error_out=False)

    return render_template(
        'admin_posts.html',
        posts=posts.items,  # Lista de postagens para a página atual
        pagination=posts     # Objeto de paginação para controle de navegação
    )




# Página de Criar Post - somente para usuários logados
@app.route('/admin/new', methods=['GET', 'POST'])
@login_required
def create_post():
    if request.method == 'POST':
        title = request.form['title']
        # Sanitizar o conteúdo antes de armazenar
        content = request.form['content']
        featured_image = request.form.get('featured_image')
        
        
        new_post = Post(
            title=title, 
            content=content, 
            featured_image=featured_image,
            )
        
        db.session.add(new_post)
        db.session.commit()
        
        return redirect(url_for('admin_posts'))
    
    return render_template('create_post.html')

# Rota para Editar um Post
@app.route('/admin/edit/<int:post_id>', methods=['GET', 'POST'])
@login_required
def edit_post(post_id):
    post = Post.query.get_or_404(post_id)
    if request.method == 'POST':
        post.title = request.form['title']
        post.content = request.form['content']
        post.featured_image = request.form.get('featured_image')
        
        db.session.commit()
        
        # Exibir uma mensagem de sucesso
        flash('Atualizado com sucesso!', 'success')
        
        # Redireciona de volta para a página de edição
        return redirect(url_for('edit_post', post_id=post.id))
    
    return render_template('edit_post.html', post=post)

# Rota para Excluir um Post
@app.route('/admin/delete/<int:post_id>', methods=['POST'])
@login_required
def delete_post(post_id):
    post = Post.query.get_or_404(post_id)
    db.session.delete(post)
    db.session.commit()
    return redirect(url_for('admin_posts'))

# Página de Visualização Completa do Post
@app.route('/post/<int:post_id>')
def post_detail(post_id):
    post = Post.query.get_or_404(post_id)
    # Incrementar o contador de visualizações do post
    post.views += 1
    db.session.commit()

    
    # Carregar os primeiros 10 comentários
     # Carregar todos os comentários para o post específico
    comments = Comment.query.filter_by(post_id=post_id).order_by(Comment.created_at.desc()).all()

   # Debug para verificar a consulta
    print("Comentários carregados para o post_id:", post_id, "->", comments)
    
    return render_template(
        'post_detail.html',
        post=post,
        author_name=AUTHOR_NAME,
        author_bio=AUTHOR_BIO,
        author_image=AUTHOR_IMAGE,
        comments=comments)

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        create_admin()
        if SiteMetrics.query.first() is None:
            db.session.add(SiteMetrics(total_visits=0))
            db.session.commit()
    app.run(debug=True)
