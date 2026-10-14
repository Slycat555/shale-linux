#pragma once
// Shale window decoration: a Windows 11 style title bar. Left-aligned title, and
// full-height 46 px caption buttons on the right; close turns red on hover.

#include <KDecoration3/Decoration>
#include <KDecoration3/DecorationButton>
#include <KDecoration3/DecorationButtonGroup>

#include <QVariant>

namespace Shale
{

class Decoration : public KDecoration3::Decoration
{
    Q_OBJECT
public:
    explicit Decoration(QObject *parent = nullptr, const QVariantList &args = {});
    ~Decoration() override;

    bool init() override;
    void paint(QPainter *painter, const QRectF &repaintArea) override;

    qreal titleBarHeight() const;
    bool isMaximized() const;
    QColor titleBarColor() const;
    QColor foregroundColor() const;
    bool isDark() const;

private:
    void updateLayout();
    void updateShadow();

    KDecoration3::DecorationButtonGroup *m_leftButtons = nullptr;
    KDecoration3::DecorationButtonGroup *m_rightButtons = nullptr;
};

class Button : public KDecoration3::DecorationButton
{
    Q_OBJECT
public:
    Button(KDecoration3::DecorationButtonType type, Decoration *decoration, QObject *parent = nullptr);
    // Standalone button for the plugin factory: KDE's GTK settings module draws each
    // button on its own this way to make the window buttons of GTK apps.
    Button(QObject *parent, const QVariantList &args);
    static KDecoration3::DecorationButton *create(KDecoration3::DecorationButtonType type,
                                                  KDecoration3::Decoration *decoration, QObject *parent);
    void paint(QPainter *painter, const QRectF &repaintArea) override;

private:
    void paintGlyph(QPainter *painter, const QRectF &box) const;
    bool m_standalone = false;
};

} // namespace Shale
