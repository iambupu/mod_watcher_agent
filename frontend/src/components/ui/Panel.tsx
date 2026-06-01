import React from "react";

type PanelPadding = "none" | "sm" | "md" | "lg" | "xl";
type PanelMargin = "none" | "sm" | "md" | "lg" | "xl";
type PanelWidth = "auto" | "full" | "fit" | "sm" | "md" | "lg" | "xl";
type PanelRadius = "md" | "lg" | "xl";
type PanelShadow = "none" | "sm" | "md" | "lg";
type ElementTag = keyof Pick<
  JSX.IntrinsicElements,
  "div" | "section" | "aside" | "article" | "main" | "header" | "footer"
>;

interface BaseSurfaceProps {
  children: React.ReactNode;
  className?: string;
  as?: ElementTag;
  padding?: PanelPadding;
  margin?: PanelMargin;
  width?: PanelWidth;
  radius?: PanelRadius;
  shadow?: PanelShadow;
  bordered?: boolean;
}

type PanelProps = BaseSurfaceProps;

const paddingClass: Record<PanelPadding, string> = {
  none: "",
  sm: "p-2",
  md: "p-4",
  lg: "p-5",
  xl: "p-6",
};

const marginClass: Record<PanelMargin, string> = {
  none: "",
  sm: "m-2",
  md: "m-4",
  lg: "m-6",
  xl: "m-8",
};

const widthClass: Record<PanelWidth, string> = {
  auto: "",
  full: "w-full",
  fit: "w-fit",
  sm: "max-w-sm",
  md: "max-w-md",
  lg: "max-w-lg",
  xl: "max-w-xl",
};

const radiusClass: Record<PanelRadius, string> = {
  md: "rounded-md",
  lg: "rounded-lg",
  xl: "rounded-xl",
};

const shadowClass: Record<PanelShadow, string> = {
  none: "",
  sm: "shadow-sm",
  md: "shadow-md",
  lg: "shadow-lg",
};

export const Surface: React.FC<BaseSurfaceProps & { bg?: "white" }> = ({
  children,
  as: Tag = "div",
  className = "",
  padding = "md",
  margin = "none",
  width = "auto",
  radius = "lg",
  shadow = "none",
  bordered = false,
  bg = "white",
}) => {
  const TagName = Tag as React.ElementType;
  const borderClass = bordered ? "border border-slate-200" : "";
  const bgClass = bg === "white" ? "bg-white" : "bg-transparent";

  return (
    <TagName
      className={[
        radiusClass[radius],
        borderClass,
        bgClass,
        paddingClass[padding],
        marginClass[margin],
        widthClass[width],
        shadowClass[shadow],
        className,
      ]
        .filter(Boolean)
        .join(" ")}
    >
      {children}
    </TagName>
  );
};

export const Panel: React.FC<PanelProps> = ({
  bordered = true,
  shadow = "sm",
  ...props
}) => {
  return (
    <Surface
      bordered={bordered}
      shadow={shadow}
      {...props}
    />
  );
};
