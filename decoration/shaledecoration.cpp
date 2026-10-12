#include "shaledecoration.h"

#include <KDecoration3/DecoratedWindow>
#include <KDecoration3/DecorationSettings>
#include <KDecoration3/DecorationShadow>
#include <KPluginFactory>

#include <QPainter>
#include <QPainterPath>
#include <cmath>

K_PLUGIN_FACTORY_WITH_JSON(ShaleDecorationFactory, "shaledecoration.json", registerPlugin<Shale::Decoration>();)

namespace Shale
{
using KDecoration3::DecorationButtonType;

// Windows 11 caption metrics, in logical pixels.
constexpr qreal TitleBarHeight = 32;
constexpr qreal ButtonWidth = 46;
constexpr qreal GlyphSize = 10;
constexpr qreal TitleMargin = 12;
constexpr qreal CornerRadius = 8;
constexpr int ShadowSize = 28;
constexpr int ShadowOffset = 4; // the shadow reaches further below the window than above
const QColor CloseHover(0xc4, 0x2b, 0x1c);
const QColor ClosePressed(0xb2, 0x2a, 0x1b);

static std::weak_ptr<KDecoration3::DecorationShadow> s_shadow;

static QPainterPath titleBarPath(const QRectF &rect, qreal radius)
{
    QPainterPath path;
    if (radius <= 0) {
        path.addRect(rect);
        return path;
    }
    path.moveTo(rect.left(), rect.bottom());
    path.lineTo(rect.left(), rect.top() + radius);
    path.arcTo(QRectF(rect.left(), rect.top(), 2 * radius, 2 * radius), 180, -90);
    path.lineTo(rect.right() - radius, rect.top());
    path.arcTo(QRectF(rect.right() - 2 * radius, rect.top(), 2 * radius, 2 * radius), 90, -90);
    path.lineTo(rect.right(), rect.bottom());
    path.closeSubpath();
    return path;
}

Decoration::Decoration(QObject *parent, const QVariantList &args)
    : KDecoration3::Decoration(parent, args)
{
}

Decoration::~Decoration() = default;

bool Decoration::init()
{
    auto *w = window();
    auto s = settings();
    using Group = KDecoration3::DecorationButtonGroup;
    m_leftButtons = new Group(Group::Position::Left, this, &Button::create);
    m_rightButtons = new Group(Group::Position::Right, this, &Button::create);
    m_leftButtons->setSpacing(0);
    m_rightButtons->setSpacing(0);

    auto repaint = [this] { update(); };
    connect(w, &KDecoration3::DecoratedWindow::activeChanged, this, repaint);
    connect(w, &KDecoration3::DecoratedWindow::captionChanged, this, repaint);
    connect(w, &KDecoration3::DecoratedWindow::paletteChanged, this, repaint);
    connect(w, &KDecoration3::DecoratedWindow::widthChanged, this, &Decoration::updateLayout);
    connect(w, &KDecoration3::DecoratedWindow::maximizedChanged, this, &Decoration::updateLayout);
    connect(w, &KDecoration3::DecoratedWindow::adjacentScreenEdgesChanged, this, &Decoration::updateLayout);
    connect(s.get(), &KDecoration3::DecorationSettings::reconfigured, this, &Decoration::updateLayout);
    connect(m_leftButtons, &Group::geometryChanged, this, &Decoration::updateLayout);
    connect(m_rightButtons, &Group::geometryChanged, this, &Decoration::updateLayout);

    updateLayout();
    updateShadow();
    return true;
}

qreal Decoration::titleBarHeight() const
{
    return TitleBarHeight;
}

bool Decoration::isMaximized() const
{
    return window()->isMaximized();
}

QColor Decoration::titleBarColor() const
{
    using namespace KDecoration3;
    return window()->color(window()->isActive() ? ColorGroup::Active : ColorGroup::Inactive, ColorRole::TitleBar);
}

QColor Decoration::foregroundColor() const
{
    using namespace KDecoration3;
    return window()->color(window()->isActive() ? ColorGroup::Active : ColorGroup::Inactive, ColorRole::Foreground);
}

bool Decoration::isDark() const
{
    return titleBarColor().lightnessF() < 0.5;
}

void Decoration::updateLayout()
{
    const qreal width = window()->width();
    const bool maximized = isMaximized();
    const qreal radius = maximized ? 0 : CornerRadius;

    setBorders(QMarginsF(0, TitleBarHeight, 0, 0));
    setResizeOnlyBorders(maximized ? QMarginsF() : QMarginsF(6, 6, 6, 6));
    setTitleBar(QRectF(0, 0, width, TitleBarHeight));
    setBorderRadius(KDecoration3::BorderRadius(radius));
    // A thin dark frame (never a light one), like Windows 11 in dark mode.
    setBorderOutline(maximized ? KDecoration3::BorderOutline()
                               : KDecoration3::BorderOutline(1, QColor(0, 0, 0, 170), KDecoration3::BorderRadius(radius)));

    const QSignalBlocker blockLeft(m_leftButtons);
    const QSignalBlocker blockRight(m_rightButtons);
    for (auto *group : {m_leftButtons, m_rightButtons}) {
        for (auto *button : group->buttons()) {
            button->setGeometry(QRectF(0, 0, ButtonWidth, TitleBarHeight));
        }
    }
    m_leftButtons->setPos(QPointF(0, 0));
    m_rightButtons->setPos(QPointF(width - m_rightButtons->geometry().width(), 0));
    update();
}

void Decoration::updateShadow()
{
    auto shadow = s_shadow.lock();
    if (!shadow) {
        // A soft, slightly downward shadow; KWin stretches the middle row and column.
        const int size = 2 * ShadowSize + 1;
        QImage image(size, size, QImage::Format_ARGB32_Premultiplied);
        image.fill(Qt::transparent);
        const qreal sigma = ShadowSize / 2.6;
        for (int y = 0; y < size; ++y) {
            for (int x = 0; x < size; ++x) {
                const qreal dx = x - ShadowSize;
                const qreal dy = y - ShadowSize - ShadowOffset;
                const qreal d = std::sqrt(dx * dx + dy * dy);
                const int alpha = qRound(255 * 0.38 * std::exp(-d * d / (2 * sigma * sigma)));
                image.setPixel(x, y, qPremultiply(qRgba(0, 0, 0, alpha)));
            }
        }
        shadow = std::make_shared<KDecoration3::DecorationShadow>();
        shadow->setShadow(image);
        shadow->setPadding(QMarginsF(ShadowSize, ShadowSize, ShadowSize, ShadowSize));
        shadow->setInnerShadowRect(QRectF(ShadowSize, ShadowSize, 1, 1));
        s_shadow = shadow;
    }
    setShadow(shadow);
}

void Decoration::paint(QPainter *painter, const QRectF &repaintArea)
{
    const QRectF bar(0, 0, window()->width(), TitleBarHeight);
    const QPainterPath path = titleBarPath(bar, isMaximized() ? 0 : CornerRadius);

    painter->save();
    painter->setRenderHint(QPainter::Antialiasing);
    painter->setPen(Qt::NoPen);
    painter->setBrush(titleBarColor());
    painter->drawPath(path);
    painter->setClipPath(path);

    // Title: left-aligned like Windows, after any left-hand buttons.
    const qreal left = m_leftButtons->buttons().isEmpty() ? TitleMargin : m_leftButtons->geometry().right() + 4;
    const qreal right = m_rightButtons->geometry().left() - TitleMargin;
    if (right > left) {
        QColor text = foregroundColor();
        if (!window()->isActive()) {
            text.setAlphaF(0.55);
        }
        painter->setFont(settings()->font());
        painter->setPen(text);
        const QRectF titleRect(left, 0, right - left, TitleBarHeight);
        const QString caption = painter->fontMetrics().elidedText(window()->caption(), Qt::ElideRight, int(titleRect.width()));
        painter->drawText(titleRect, Qt::AlignLeft | Qt::AlignVCenter | Qt::TextSingleLine, caption);
    }

    m_leftButtons->paint(painter, repaintArea);
    m_rightButtons->paint(painter, repaintArea);
    painter->restore();
}

Button::Button(DecorationButtonType type, Decoration *decoration, QObject *parent)
    : KDecoration3::DecorationButton(type, decoration, parent)
{
    // Visibility, checked state and click actions are handled by DecorationButton itself.
    setGeometry(QRectF(0, 0, ButtonWidth, TitleBarHeight));
    connect(this, &DecorationButton::hoveredChanged, this, [this] { update(); });
    connect(this, &DecorationButton::pressedChanged, this, [this] { update(); });
    connect(this, &DecorationButton::checkedChanged, this, [this] { update(); });
}

KDecoration3::DecorationButton *Button::create(DecorationButtonType type, KDecoration3::Decoration *decoration, QObject *parent)
{
    auto *deco = qobject_cast<Decoration *>(decoration);
    if (!deco) {
        return nullptr;
    }
    switch (type) {
    case DecorationButtonType::Menu:
    case DecorationButtonType::ApplicationMenu:
    case DecorationButtonType::OnAllDesktops:
    case DecorationButtonType::Minimize:
    case DecorationButtonType::Maximize:
    case DecorationButtonType::Close:
    case DecorationButtonType::ContextHelp:
    case DecorationButtonType::Shade:
    case DecorationButtonType::KeepAbove:
    case DecorationButtonType::KeepBelow:
        return new Button(type, deco, parent);
    default:
        return nullptr;
    }
}

void Button::paint(QPainter *painter, const QRectF &repaintArea)
{
    Q_UNUSED(repaintArea)
    if (!isVisible()) {
        return;
    }
    auto *deco = static_cast<Decoration *>(decoration());
    const QRectF rect = geometry();
    const bool close = type() == DecorationButtonType::Close;
    const bool dark = deco->isDark();

    painter->save();
    painter->setRenderHint(QPainter::Antialiasing);

    // Background: red for close, a faint wash for the others (Windows 11 values).
    QColor background = Qt::transparent;
    if (close && (isHovered() || isPressed())) {
        background = isPressed() ? ClosePressed : CloseHover;
    } else if (isPressed()) {
        background = dark ? QColor(255, 255, 255, 11) : QColor(0, 0, 0, 6);
    } else if (isHovered() || (isChecked() && type() != DecorationButtonType::Maximize)) {
        background = dark ? QColor(255, 255, 255, 15) : QColor(0, 0, 0, 10);
    }
    if (background.alpha() > 0) {
        painter->fillRect(rect, background);
    }

    QColor glyph = deco->foregroundColor();
    if (close && (isHovered() || isPressed())) {
        glyph = Qt::white;
    } else if (!deco->window()->isActive() && !isHovered()) {
        glyph.setAlphaF(0.45);
    }
    if (!isEnabled()) {
        glyph.setAlphaF(0.3);
    }
    QPen pen(glyph, 1.0);
    pen.setCapStyle(Qt::FlatCap);
    pen.setJoinStyle(Qt::MiterJoin);
    painter->setPen(pen);
    painter->setBrush(Qt::NoBrush);

    const QRectF box(std::round(rect.center().x() - GlyphSize / 2) + 0.5,
                     std::round(rect.center().y() - GlyphSize / 2) + 0.5, GlyphSize, GlyphSize);
    paintGlyph(painter, box);
    painter->restore();
}

void Button::paintGlyph(QPainter *painter, const QRectF &b) const
{
    const qreal x = b.left(), y = b.top(), s = b.width();
    switch (type()) {
    case DecorationButtonType::Minimize:
        painter->drawLine(QPointF(x, y + s / 2), QPointF(x + s, y + s / 2));
        break;
    case DecorationButtonType::Maximize:
        if (isChecked()) {
            // Restore: a square with a second one peeking out behind it.
            painter->drawRoundedRect(QRectF(x, y + 2, s - 2, s - 2), 1, 1);
            QPainterPath back;
            back.moveTo(x + 2, y + 2);
            back.lineTo(x + 2, y + 1);
            back.quadTo(x + 2, y, x + 3, y);
            back.lineTo(x + s - 1, y);
            back.quadTo(x + s, y, x + s, y + 1);
            back.lineTo(x + s, y + s - 3);
            back.lineTo(x + s - 2, y + s - 3);
            painter->drawPath(back);
        } else {
            painter->drawRoundedRect(b, 1, 1);
        }
        break;
    case DecorationButtonType::Close:
        painter->drawLine(b.topLeft(), b.bottomRight());
        painter->drawLine(b.topRight(), b.bottomLeft());
        break;
    case DecorationButtonType::Menu: {
        const QRectF iconRect(b.center().x() - 8, b.center().y() - 8, 16, 16);
        decoration()->window()->icon().paint(painter, iconRect.toRect());
        break;
    }
    case DecorationButtonType::ApplicationMenu:
        for (int i = 0; i < 3; ++i) {
            const qreal ly = y + 1 + i * (s - 2) / 2;
            painter->drawLine(QPointF(x, ly), QPointF(x + s, ly));
        }
        break;
    case DecorationButtonType::OnAllDesktops:
        painter->setBrush(isChecked() ? painter->pen().color() : Qt::transparent);
        painter->drawEllipse(b.adjusted(2, 2, -2, -2));
        break;
    case DecorationButtonType::KeepAbove:
        painter->drawPolyline(QPolygonF({QPointF(x, y + s * 0.7), QPointF(x + s / 2, y + s * 0.2), QPointF(x + s, y + s * 0.7)}));
        break;
    case DecorationButtonType::KeepBelow:
        painter->drawPolyline(QPolygonF({QPointF(x, y + s * 0.3), QPointF(x + s / 2, y + s * 0.8), QPointF(x + s, y + s * 0.3)}));
        break;
    case DecorationButtonType::Shade:
        painter->drawLine(QPointF(x, y + 1), QPointF(x + s, y + 1));
        painter->drawPolyline(QPolygonF({QPointF(x + 1, y + s * 0.85), QPointF(x + s / 2, y + s * 0.4), QPointF(x + s - 1, y + s * 0.85)}));
        break;
    case DecorationButtonType::ContextHelp: {
        QFont font = painter->font();
        font.setPixelSize(int(s * 1.3));
        painter->setFont(font);
        painter->drawText(b.adjusted(-4, -4, 4, 4), Qt::AlignCenter, QStringLiteral("?"));
        break;
    }
    default:
        break;
    }
}

} // namespace Shale

#include "shaledecoration.moc"
