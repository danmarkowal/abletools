from pathlib import Path
from typing import Any, Dict


from lxml import etree


from abletools.plugins.component_extractor import Uid
from abletools.plugins.patch_registry import PatchRegistry
from abletools.plugins.vst_id_converter import VstIdConversionError, VstIdConverter
from abletools.utils.xml_converter import XMLConversionError, XMLConverter, copy_tags, find_not_null, format_long_text_element, get_tagged_value, make_tagged_value, map_tag


class VstConversionContext:
    def __init__(self, uid_cache_path: Path, patch_registry: PatchRegistry):
        self._uid_cache_path = uid_cache_path
        self._patch_registry = patch_registry
        # plugin_name, vendor, plugin_version, plugin_path, vst_version, plugin_id, current_program, is_on
        self._metadata: Dict[str, Any] = {}

    @property
    def uid_cache_path(self) -> Path:
        return self._uid_cache_path

    @property
    def patch_registry(self) -> PatchRegistry:
        return self._patch_registry

    @property
    def metadata(self) -> Dict[str, Any]:
        return dict(self._metadata)  # Return a read-only copy

    def set_meta_value(self, key: str, value: Any) -> None:
        self._metadata[key] = value


class Vst3Converter(XMLConverter):
    # These tags are the same in VST2 and VST3 plugin info, so we can just copy them over without modification
    SAME_TAGS = ["WinPosX", "WinPosY", "NumAudioInputs",
                 "NumAudioOutputs", "IsPlaceholderDevice"]

    def __init__(self, ctx: VstConversionContext):
        self.ctx = ctx

    def convert(self, root: etree.Element) -> etree.Element:
        # <Vst3PluginInfo Id="12345">
        vst3_info = etree.Element("Vst3PluginInfo")
        # IDK whether you can have more than one Vst3PluginInfo in a plugin descriptor tag
        vst3_info.set("Id", root.get("Id", "0"))

        plugin_id = get_tagged_value(root, "UniqueId", str)
        plugin_path = get_tagged_value(root, "Path", Path)
        plugin_name = get_tagged_value(root, "PlugName", str)
        plugin_version = get_tagged_value(root, "Version", str)
        vst_version = get_tagged_value(root, "VstVersion", str)

        self.ctx.set_meta_value("plugin_id", plugin_id)
        self.ctx.set_meta_value("plugin_path", plugin_path)
        self.ctx.set_meta_value("plugin_name", plugin_name)
        self.ctx.set_meta_value("plugin_version", plugin_version)
        self.ctx.set_meta_value("vst_version", vst_version)

        copy_tags(root, vst3_info, self.SAME_TAGS)

        try:
            uid = VstIdConverter(self.ctx.uid_cache_path).convert_to_uid(
                plugin_path, plugin_id)
        except VstIdConversionError as e:
            raise XMLConversionError(
                f"Failed to convert UID of VST2 plugin at path '{plugin_path}'. Error {e}")

        # <Preset Id="12345">
        vst3_info.append(
            VstPresetConverter(self.ctx, uid).convert(find_not_null(root, "Preset")))

        # <Name>
        map_tag(root, vst3_info, "PlugName", "Name")

        # <Uid>
        vst3_info.append(_make_uid_element(uid))

        return vst3_info


class VstPresetConverter(XMLConverter):
    # These go before the Processor and Controller states
    # I'm not sure if the order matters, but we might as well keep it consistent
    SAME_TAGS_1 = ["OverwriteProtectionNumber",
                   "MpeEnabled", "MpeSettings",
                   "ParameterSettings", "IsOn",
                   "PowerMacroControlIndex",
                   "PowerMacroMappingRange",
                   "IsFolded",
                   "StoredAllParameters",
                   "DeviceLomId",
                   "DeviceViewLomId",
                   "IsOnLomId",
                   "ParametersListWrapperLomId"]
    # These go after the Processor and Controller states
    SAME_TAGS_2 = ["Name", "PresetRef"]

    def __init__(self, ctx: VstConversionContext, uid: Uid):
        self.ctx = ctx
        self.uid = uid

    def convert(self, root: etree.Element) -> etree.Element:
        # root:
        #   <Preset>
        #       <VstPreset Id="12345">
        #       ...
        #       </VstPreset>
        #   </Preset>
        vst2_preset = find_not_null(root, "VstPreset")
        vst3_preset = etree.Element("Vst3Preset")
        vst3_preset.set("Id", vst2_preset.get("Id", "0"))

        # Extract values BEFORE copying tags to present missing tag errors
        program_number = get_tagged_value(vst2_preset, "ProgramNumber", int)
        is_on = get_tagged_value(vst2_preset, "IsOn", _ableton_bool)

        self.ctx.set_meta_value("program_number", program_number)
        self.ctx.set_meta_value("is_on", is_on)

        # First set of common tags
        copy_tags(vst2_preset, vst3_preset, self.SAME_TAGS_1)

        # Add <Uid>
        vst3_preset.append(_make_uid_element(self.uid))

        # Add <DeviceType>

        # Add <ProcessorState>
        plugin_data = VstPluginDataConverter(self.ctx).convert(
            find_not_null(vst2_preset, "Buffer"))
        format_long_text_element(plugin_data)
        vst3_preset.append(plugin_data)

        # Add <ControllerState> (IDK whether this is supposed to have any contents)
        vst3_preset.append(etree.Element("ControllerState"))

        # Second set of common tags
        copy_tags(vst2_preset, vst3_preset, self.SAME_TAGS_2)

        new_preset = etree.Element("Preset")
        new_preset.append(vst3_preset)
        return new_preset


class VstPluginDataConverter(XMLConverter):
    def __init__(self, ctx: VstConversionContext):
        self.ctx = ctx

    def convert(self, root: etree.Element) -> etree.Element:
        # root:
        #   <Buffer>
        #     ... (buffer data)
        #   </Buffer>
        buffer_contents = root.text
        if buffer_contents is None:
            raise XMLConversionError(
                f"Buffer contents for element '{root.getroottree().getpath(root)}' are empty.")

        buffer_contents = self.ctx.patch_registry.apply_user_patch(
            self._sanitize_buffer_contents(buffer_contents), self.ctx.metadata)

        vst3_state = etree.Element("ProcessorState")
        vst3_state.text = buffer_contents
        return vst3_state

    def _sanitize_buffer_contents(self, buffer_contents: str) -> str:
        # We need to remove spaces, newlines, tabs etc. so that binascii doesn't complain
        return "".join(buffer_contents.split())


def _make_uid_element(uid_fields: Uid) -> etree.Element:
    uid_element = etree.Element("Uid")
    for i, field in enumerate(uid_fields):
        uid_element.append(make_tagged_value(f"Fields.{i}", str(field)))
    return uid_element


def _ableton_bool(value: str) -> bool:
    if value == "true":
        return True
    if value == "false":
        return False
    raise ValueError(f"Ableton boolean must be either 'true' or 'false'.")
